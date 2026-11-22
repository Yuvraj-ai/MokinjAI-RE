from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, delete, func, literal, or_, select, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.middleware.rbac import require_workspace_role
from app.models.external_database import ExternalDatabaseConnection
from app.models.agent import (
    Agent,
    AgentConnector,
    AgentDataSource,
    AgentDocument,
    AgentSkill,
    AgentSubagent,
    AgentTool,
)
from app.models.connector import ConnectorInstance
from app.models.execution import Execution
from app.models.knowledge import Document, FileFolder
from app.models.llm_profile import LlmProfile
from app.models.resource_usage import ResourceUsage, bump_usage
from app.models.search_credential import SearchCredential
from app.models.skill import Skill
from app.models.structured_output import StructuredOutput
from app.models.tool import Tool
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.schemas.agent import (
    AgentDataSourceItem,
    AgentDocumentItem,
    AgentCapabilitiesResponse,
    AgentListItem,
    AgentListResponse,
    AgentOption,
    AgentOptionsResponse,
    AgentResponse,
    AgentWriteRequest,
    ResolvedDependencies,
    ResolvedSkill,
    ResolvedTool,
)
from app.services.agent_capabilities import capabilities_for
from app.services.agent_composition import (
    AgentInput,
    DataSourceRule,
    FolderRule,
    CompositionError,
    assert_name_is_free,
    join_ids,
    validate_agent,
)
from app.services.agent_dependencies import effective_tool_names, resolve_skills
from app.services.agent_validation import AgentValidationError, normalise_params
from app.services.skill import SkillDefinition, SkillError, extract_references
from app.services.structured_output import (
    Definition,
    StructuredOutputError,
    compile_schema,
)
from app.services.tool_schema import extract_schema, extraction_error
from app.utils.errors import ConflictException, NotFoundException

router = APIRouter()


def _input(request: AgentWriteRequest) -> AgentInput:
    return AgentInput(
        name=request.name,
        description=request.description,
        llm_profile_id=request.llm_profile_id,
        system_prompt=request.system_prompt,
        source_prompt_id=request.source_prompt_id,
        params=request.params,
        structured_output_id=request.structured_output_id,
        web_search=request.web_search,
        skill_ids=request.skill_ids,
        tool_ids=request.tool_ids,
        folders=[
            FolderRule(id=rule.id, exclude_document_ids=list(rule.exclude_document_ids))
            for rule in request.folders
        ],
        documents=list(request.documents),
        data_sources=[
            DataSourceRule(id=rule.id, tables=list(rule.tables))
            for rule in request.data_sources
        ],
        connector_ids=request.connector_ids,
        subagent_ids=request.subagent_ids,
    )


def _raise_composition(exc: CompositionError) -> None:
    raise HTTPException(
        status_code=422,
        detail=[
            {"loc": ["body", error.field], "msg": error.message, "type": "value_error"}
            for error in exc.errors
        ],
    )


async def _load_agent(db: AsyncSession, workspace_id: str, agent_id: str) -> Agent:
    row = (
        await db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.workspace_id == workspace_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundException("Agent")
    return row


async def _join_ids(db: AsyncSession, agent_id: str) -> dict[str, list[str]]:
    # UNUSED: responses read joins through `_load_read_context`. Marked for later removal.
    return await join_ids(db, agent_id)


def _add_joins(db: AsyncSession, agent_id: str, ids: dict[str, list[str]]) -> None:
    db.add_all([AgentSkill(agent_id=agent_id, skill_id=value) for value in ids["skill_ids"]])
    db.add_all([AgentTool(agent_id=agent_id, tool_id=value) for value in ids["tool_ids"]])
    db.add_all(
        [
            AgentConnector(agent_id=agent_id, connector_instance_id=value)
            for value in ids["connector_ids"]
        ]
    )
    db.add_all(
        [AgentSubagent(agent_id=agent_id, subagent_id=value) for value in ids["subagent_ids"]]
    )


def _add_attachments(db: AsyncSession, agent_id: str, validated) -> None:
    """One row per resolved file; a folder is only its source, never a live rule."""
    db.add_all(
        [
            AgentDocument(
                agent_id=agent_id,
                document_id=row.id,
                source_folder_id=validated.attachment_sources.get(row.id),
            )
            for row in validated.attached_documents
        ]
    )


def _add_data_sources(db: AsyncSession, agent_id: str, validated) -> None:
    """One allowlist row per attached connection; the tables list is the snapshot."""
    db.add_all(
        [
            AgentDataSource(
                agent_id=agent_id,
                connection_id=item.connection.id,
                tables=list(item.tables),
            )
            for item in validated.data_sources
        ]
    )


async def _replace_joins(db: AsyncSession, agent_id: str, ids: dict[str, list[str]]) -> None:
    for model in (AgentSkill, AgentTool, AgentConnector, AgentSubagent, AgentDocument):
        await db.execute(delete(model).where(model.agent_id == agent_id))
    await db.execute(delete(AgentDataSource).where(AgentDataSource.agent_id == agent_id))
    _add_joins(db, agent_id, ids)


def _ids_from_validated(validated) -> dict[str, list[str]]:
    return {
        "skill_ids": [row.id for row in validated.selected_skills],
        "tool_ids": [row.id for row in validated.direct_tools],
        "connector_ids": [row.id for row in validated.connectors],
        "subagent_ids": [row.id for row in validated.subagents],
    }


def _capabilities_response(profile: LlmProfile | None) -> AgentCapabilitiesResponse | None:
    if profile is None:
        return None
    try:
        capabilities = capabilities_for(
            profile.provider,
            profile.model_id,
            max_output_tokens_override=profile.max_output_tokens,
            context_window=profile.context_window,
        )
    except ValueError:
        return None
    return AgentCapabilitiesResponse(**capabilities.as_dict())


@dataclass
class _ReadContext:
    """Everything the agent responses read, loaded once for a batch of agents.

    Each field is one query (or none when no agent needs it), so building the
    list costs the same number of round trips for one agent or a hundred.
    """

    profiles: dict[str, LlmProfile]
    skills: list[Skill]
    tools: list[Tool]
    outputs: dict[str, StructuredOutput]
    search_providers: set[str]
    joins: dict[str, dict[str, list[str]]]
    connectors: dict[str, ConnectorInstance]
    data_sources: dict[str, list[AgentDataSource]]
    connection_names: dict[str, str]
    attachments: dict[str, list[tuple[Document, str | None]]]
    # Tool code is parsed once per request, not once per agent that uses it.
    schema_errors: dict[str, str | None] = field(default_factory=dict)

    def schema_error(self, tool: Tool) -> str | None:
        if tool.id not in self.schema_errors:
            extracted = extract_schema(tool.code)
            self.schema_errors[tool.id] = (
                None if extracted.schema is not None else extraction_error(tool.name, extracted)
            )
        return self.schema_errors[tool.id]


_JOIN_TABLES = (
    ("skill_ids", AgentSkill, AgentSkill.skill_id),
    ("tool_ids", AgentTool, AgentTool.tool_id),
    ("documents", AgentDocument, AgentDocument.document_id),
    ("connector_ids", AgentConnector, AgentConnector.connector_instance_id),
    ("subagent_ids", AgentSubagent, AgentSubagent.subagent_id),
)


async def _load_read_context(
    db: AsyncSession, workspace_id: str, agents: list[Agent]
) -> _ReadContext:
    agent_ids = [agent.id for agent in agents]

    async def rows(statement) -> list:
        return list((await db.execute(statement)).scalars().all())

    profile_ids = {agent.llm_profile_id for agent in agents if agent.llm_profile_id}
    profiles = (
        {row.id: row for row in await rows(select(LlmProfile).where(LlmProfile.id.in_(profile_ids)))}
        if profile_ids
        else {}
    )
    skills = await rows(select(Skill).where(Skill.workspace_id == workspace_id))
    tools = await rows(select(Tool).where(Tool.workspace_id == workspace_id))

    output_ids = {agent.structured_output_id for agent in agents if agent.structured_output_id}
    outputs = (
        {
            row.id: row
            for row in await rows(
                select(StructuredOutput).where(
                    or_(
                        StructuredOutput.workspace_id == workspace_id,
                        StructuredOutput.id.in_(output_ids),
                    )
                )
            )
        }
        if output_ids
        else {}
    )

    wants_search = any(
        agent.web_search and agent.web_search.get("method") in ("tavily", "exa") for agent in agents
    )
    search_providers = (
        set(
            await rows(
                select(SearchCredential.provider).where(
                    SearchCredential.workspace_id == workspace_id
                )
            )
        )
        if wants_search
        else set()
    )

    joins = {
        agent_id: {name: [] for name, _, _ in _JOIN_TABLES} for agent_id in agent_ids
    }
    if agent_ids:
        statement = union_all(
            *(
                select(
                    literal(name).label("kind"),
                    model.agent_id.label("agent_id"),
                    column.label("ref"),
                ).where(model.agent_id.in_(agent_ids))
                for name, model, column in _JOIN_TABLES
            )
        )
        for kind, agent_id, ref in (await db.execute(statement)).all():
            joins[agent_id][kind].append(ref)

    connector_ids = {ref for ids in joins.values() for ref in ids["connector_ids"]}
    connectors = (
        {
            row.id: row
            for row in await rows(
                select(ConnectorInstance).where(
                    ConnectorInstance.id.in_(connector_ids),
                    ConnectorInstance.workspace_id == workspace_id,
                )
            )
        }
        if connector_ids
        else {}
    )

    data_sources: dict[str, list[AgentDataSource]] = {agent_id: [] for agent_id in agent_ids}
    if agent_ids:
        for row in await rows(
            select(AgentDataSource).where(AgentDataSource.agent_id.in_(agent_ids))
        ):
            data_sources[row.agent_id].append(row)
    connection_names = (
        {
            row.id: row.name
            for row in await rows(
                select(ExternalDatabaseConnection).where(
                    ExternalDatabaseConnection.workspace_id == workspace_id
                )
            )
        }
        if any(data_sources.values())
        else {}
    )

    attachments: dict[str, list[tuple[Document, str | None]]] = {
        agent_id: [] for agent_id in agent_ids
    }
    if agent_ids:
        result = await db.execute(
            select(Document, AgentDocument.source_folder_id, AgentDocument.agent_id)
            .join(AgentDocument, AgentDocument.document_id == Document.id)
            .where(AgentDocument.agent_id.in_(agent_ids))
            .order_by(AgentDocument.created_at, AgentDocument.document_id)
        )
        for document, source_folder_id, agent_id in result.all():
            attachments[agent_id].append((document, source_folder_id))

    return _ReadContext(
        profiles=profiles,
        skills=skills,
        tools=tools,
        outputs=outputs,
        search_providers=search_providers,
        joins=joins,
        connectors=connectors,
        data_sources=data_sources,
        connection_names=connection_names,
        attachments=attachments,
    )


async def _to_response(
    db: AsyncSession, agent: Agent, *, join_ids: dict[str, list[str]] | None = None
) -> AgentResponse:
    context = await _load_read_context(db, agent.workspace_id, [agent])
    if join_ids is not None:
        context.joins[agent.id] = join_ids
    return _build_response(agent, context)


def _build_response(agent: Agent, context: _ReadContext) -> AgentResponse:
    """The agent's response and readiness, from already-loaded data (no queries)."""
    ids = context.joins[agent.id]
    profile = context.profiles.get(agent.llm_profile_id) if agent.llm_profile_id else None
    capabilities = _capabilities_response(profile)

    all_skills = context.skills
    selected_skills = [row for row in all_skills if row.id in ids["skill_ids"]]
    selected_names = {row.name for row in selected_skills}

    issues: list[str] = []
    if profile is None:
        issues.append("Select a verified LLM profile.")
    elif profile.status != "verified":
        issues.append(f"The selected LLM profile is {profile.status}.")

    resolved_skills = None
    try:
        resolved_skills = resolve_skills(
            [row.name for row in selected_skills],
            {
                row.name: SkillDefinition(
                    name=row.name, description=row.description, content=row.content
                )
                for row in all_skills
            },
        )
    except SkillError as exc:
        issues.append(str(exc))

    if capabilities is not None:
        try:
            normalise_params(agent.params, capabilities)
        except AgentValidationError as exc:
            issues.extend(f"{error.field}: {error.message}" for error in exc.errors)

    if agent.structured_output_id:
        output = context.outputs.get(agent.structured_output_id)
        if output is None:
            issues.append("The selected structured output was deleted.")
        else:
            try:
                compile_schema(
                    Definition(
                        name=output.name,
                        description=output.description,
                        fields=list(output.fields or []),
                    ),
                    {
                        row.name: Definition(
                            name=row.name,
                            description=row.description,
                            fields=list(row.fields or []),
                        )
                        for row in context.outputs.values()
                        if row.workspace_id == agent.workspace_id
                    },
                )
            except StructuredOutputError as exc:
                issues.append(f"structured output: {exc}")

    if agent.web_search and agent.web_search.get("method") in ("tavily", "exa"):
        method = agent.web_search["method"]
        if method not in context.search_providers:
            issues.append(f"Add an API key for {method}.")

    for connector_id in ids["connector_ids"]:
        connector = context.connectors.get(connector_id)
        if connector is not None and connector.status != "enabled":
            issues.append(f"Connector {connector.name} is {connector.status}.")

    all_tools = context.tools
    direct_tools = [row for row in all_tools if row.id in ids["tool_ids"]]
    workspace_tools = {row.name.lower(): row for row in all_tools}
    required = {name.lower() for name in (resolved_skills.tool_names if resolved_skills else ())}
    tool_names = effective_tool_names(
        resolved_skills.tool_names if resolved_skills else (),
        [row.name for row in direct_tools],
    )
    for name in tool_names:
        row = workspace_tools.get(name.lower())
        if row is None:
            continue
        error = context.schema_error(row)
        if error is not None:
            issues.append(error)

    resolved = ResolvedDependencies(
        skills=[
            ResolvedSkill(
                id=next(
                    (
                        row.id
                        for row in all_skills
                        if row.name.lower() == name.lower()
                    ),
                    "",
                ),
                name=name,
                root=name in selected_names,
            )
            for name in (resolved_skills.skill_closure if resolved_skills else ())
        ],
        tools=[
            ResolvedTool(
                name=workspace_tools[name.lower()].name if name.lower() in workspace_tools else name,
                source="workspace" if name.lower() in workspace_tools else "builtin",
                locked=name.lower() in required,
                tool_id=workspace_tools[name.lower()].id if name.lower() in workspace_tools else None,
            )
            for name in tool_names
        ],
    )

    data_source_rows = context.data_sources[agent.id]

    return AgentResponse(
        id=agent.id,
        workspace_id=agent.workspace_id,
        name=agent.name,
        description=agent.description,
        llm_profile_id=agent.llm_profile_id,
        system_prompt=agent.system_prompt,
        source_prompt_id=agent.source_prompt_id,
        params=agent.params or {},
        structured_output_id=agent.structured_output_id,
        web_search=agent.web_search,
        skill_ids=ids["skill_ids"],
        tool_ids=ids["tool_ids"],
        documents=[
            AgentDocumentItem(
                id=document.id,
                filename=document.filename,
                folder_id=document.folder_id,
                source_folder_id=source_folder_id,
            )
            for document, source_folder_id in context.attachments[agent.id]
        ],
        data_sources=[
            AgentDataSourceItem(
                id=row.connection_id,
                name=context.connection_names.get(row.connection_id, row.connection_id),
                tables=list(row.tables or []),
            )
            for row in data_source_rows
        ],
        connector_ids=ids["connector_ids"],
        subagent_ids=ids["subagent_ids"],
        resolved=resolved,
        capabilities=capabilities,
        status="needs_attention" if issues else "ready",
        issues=issues,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def _ordered(model, resource_type: str):
    return (
        select(model)
        .outerjoin(
            ResourceUsage,
            and_(
                ResourceUsage.workspace_id == model.workspace_id,
                ResourceUsage.resource_type == resource_type,
                ResourceUsage.resource_id == model.id,
            ),
        )
        .order_by(
            func.coalesce(ResourceUsage.last_used_at, model.created_at).desc(),
            model.name,
        )
    )


@router.get("/options", response_model=AgentOptionsResponse)
async def agent_options(
    workspace_id: str,
    agent_id: str | None = Query(None),
    _member: WorkspaceMember = Depends(require_workspace_role("viewer")),
    db: AsyncSession = Depends(get_db),
):
    profiles = list(
        (
            await db.execute(
                _ordered(LlmProfile, "llm_profile").where(
                    LlmProfile.workspace_id == workspace_id,
                    LlmProfile.status == "verified",
                )
            )
        )
        .scalars()
        .all()
    )
    outputs = list(
        (
            await db.execute(
                _ordered(StructuredOutput, "structured_output").where(
                    StructuredOutput.workspace_id == workspace_id
                )
            )
        )
        .scalars()
        .all()
    )
    skills = list(
        (
            await db.execute(
                _ordered(Skill, "skill").where(Skill.workspace_id == workspace_id)
            )
        )
        .scalars()
        .all()
    )
    connectors = list(
        (
            await db.execute(
                _ordered(ConnectorInstance, "connector").where(
                    ConnectorInstance.workspace_id == workspace_id
                )
            )
        )
        .scalars()
        .all()
    )
    tools = list(
        (
            await db.execute(
                _ordered(Tool, "tool").where(Tool.workspace_id == workspace_id)
            )
        )
        .scalars()
        .all()
    )
    agents_query = _ordered(Agent, "agent").where(Agent.workspace_id == workspace_id)
    if agent_id:
        agents_query = agents_query.where(Agent.id != agent_id)
    agents = list((await db.execute(agents_query)).scalars().all())

    def tool_description(code: str) -> str | None:
        extracted = extract_schema(code)
        return extracted.schema.description if extracted.schema else None

    skill_options = []
    for row in skills:
        references = extract_references(row.content)
        skill_options.append(
            AgentOption(
                id=row.id,
                name=row.name,
                description=row.description,
                skill_refs=references.skill_refs,
                tool_refs=references.tool_refs,
            )
        )

    return AgentOptionsResponse(
        llm_profiles=[
            AgentOption(
                id=row.id,
                name=row.name,
                provider=row.provider,
                model_id=row.model_id,
                status=row.status,
                capabilities=_capabilities_response(row),
            )
            for row in profiles
        ],
        structured_outputs=[
            AgentOption(id=row.id, name=row.name, description=row.description) for row in outputs
        ],
        skills=skill_options,
        connectors=[
            AgentOption(id=row.id, name=row.name, status=row.status) for row in connectors
        ],
        tools=[
            AgentOption(id=row.id, name=row.name, description=tool_description(row.code))
            for row in tools
        ],
        agents=[
            AgentOption(id=row.id, name=row.name, description=row.description) for row in agents
        ],
    )


@router.get("", response_model=AgentListResponse)
async def list_agents(
    workspace_id: str,
    _member: WorkspaceMember = Depends(require_workspace_role("viewer")),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(Agent)
            .where(Agent.workspace_id == workspace_id)
            .order_by(Agent.updated_at.desc())
        )
    ).scalars().all()

    # The badge comes from `_build_response`, the same checks as the detail
    # view, so the two can never disagree. All data is loaded once for the
    # whole list, so the query count does not grow with the number of agents.
    context = await _load_read_context(db, workspace_id, list(rows))
    items = []
    for agent in rows:
        status = _build_response(agent, context).status
        items.append(
            AgentListItem(
                id=agent.id,
                name=agent.name,
                description=agent.description,
                llm_profile_id=agent.llm_profile_id,
                status=status,
                updated_at=agent.updated_at,
            )
        )
    return AgentListResponse(agents=items, total=len(items))


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    workspace_id: str,
    request: AgentWriteRequest,
    current_user: User = Depends(get_current_user),
    _member: WorkspaceMember = Depends(require_workspace_role("editor")),
    db: AsyncSession = Depends(get_db),
):
    await assert_name_is_free(db, workspace_id, request.name, exclude_id=None)
    try:
        validated = await validate_agent(db, workspace_id, _input(request), agent_id=None)
    except CompositionError as exc:
        _raise_composition(exc)

    agent = Agent(
        workspace_id=workspace_id,
        name=request.name.strip(),
        description=request.description,
        llm_profile_id=validated.profile.id,
        system_prompt=request.system_prompt,
        source_prompt_id=validated.source_prompt.id if validated.source_prompt else None,
        params=validated.params,
        structured_output_id=(
            validated.structured_output.id if validated.structured_output else None
        ),
        web_search=validated.web_search,
        created_by=current_user.id,
    )
    db.add(agent)
    await db.flush()
    _add_joins(db, agent.id, _ids_from_validated(validated))
    _add_attachments(db, agent.id, validated)
    _add_data_sources(db, agent.id, validated)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ConflictException(f'An agent named "{request.name}" already exists.')

    await db.refresh(agent)
    await bump_usage(db, workspace_id, "llm_profile", validated.profile.id)
    await db.commit()
    return await _to_response(db, agent)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    workspace_id: str,
    agent_id: str,
    _member: WorkspaceMember = Depends(require_workspace_role("viewer")),
    db: AsyncSession = Depends(get_db),
):
    agent = await _load_agent(db, workspace_id, agent_id)
    return await _to_response(db, agent)


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    workspace_id: str,
    agent_id: str,
    request: AgentWriteRequest,
    _member: WorkspaceMember = Depends(require_workspace_role("editor")),
    db: AsyncSession = Depends(get_db),
):
    agent = await _load_agent(db, workspace_id, agent_id)
    await assert_name_is_free(db, workspace_id, request.name, exclude_id=agent_id)
    try:
        validated = await validate_agent(db, workspace_id, _input(request), agent_id=agent_id)
    except CompositionError as exc:
        _raise_composition(exc)

    agent.name = request.name.strip()
    agent.description = request.description
    agent.llm_profile_id = validated.profile.id
    agent.system_prompt = request.system_prompt
    agent.source_prompt_id = validated.source_prompt.id if validated.source_prompt else None
    agent.params = validated.params
    agent.structured_output_id = (
        validated.structured_output.id if validated.structured_output else None
    )
    agent.web_search = validated.web_search
    await _replace_joins(db, agent.id, _ids_from_validated(validated))
    _add_attachments(db, agent.id, validated)
    _add_data_sources(db, agent.id, validated)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ConflictException(f'An agent named "{request.name}" already exists.')

    await db.refresh(agent)
    await bump_usage(db, workspace_id, "llm_profile", validated.profile.id)
    await db.commit()
    return await _to_response(db, agent)


@router.delete("/{agent_id}")
async def delete_agent(
    workspace_id: str,
    agent_id: str,
    _member: WorkspaceMember = Depends(require_workspace_role("editor")),
    db: AsyncSession = Depends(get_db),
):
    agent = await _load_agent(db, workspace_id, agent_id)
    referrers = (
        await db.execute(
            select(Agent.name)
            .join(AgentSubagent, AgentSubagent.agent_id == Agent.id)
            .where(
                AgentSubagent.subagent_id == agent_id,
                Agent.workspace_id == workspace_id,
            )
        )
    ).scalars().all()
    if referrers:
        raise ConflictException(
            "This agent is used as a subagent by: " + ", ".join(sorted(referrers))
        )

    await db.delete(agent)
    await db.commit()
    return {"success": True}
