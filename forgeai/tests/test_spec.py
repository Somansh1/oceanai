"""Unit tests for declarative agent specification models."""
from __future__ import annotations

from forge.spec import AgentDefinition, OutputContract, RetrievalConfig, ToolBinding


def test_agent_definition_defaults_and_validation():
    defn = AgentDefinition(
        name="TestAgent",
        description="A test agent",
        system_prompt="You are a helpful assistant.",
        requirements_digest="Scope: shore HR policy; audience: staff; tone: formal",
        retrieval=RetrievalConfig(top_k_dense=4, top_k_sparse=6),
        tools=[
            ToolBinding(
                name="calculator",
                justification="Demurrage arithmetic required by brief",
                invoked_when="Evaluating pro-rated leave and demurrage rates",
            )
        ],
        output_contract=OutputContract(),
    )

    dumped = defn.model_dump_json()
    loaded = AgentDefinition.model_validate_json(dumped)

    assert loaded.name == "TestAgent"
    assert loaded.retrieval.top_k_dense == 4
    assert len(loaded.tools) == 1
    assert loaded.tools[0].name == "calculator"
    assert loaded.tools[0].invoked_when == "Evaluating pro-rated leave and demurrage rates"
    assert loaded.output_contract.to_json_schema()["type"] == "object"
