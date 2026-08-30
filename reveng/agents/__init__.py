"""
Agents Domain — agent identity, structure, and internal sections.

AgentSpec is the canonical internal definition of an agent.
AgentRecord (in storage) serializes/deserializes AgentSpec.
"""
__all__ = ["AgentSpec"]
from reveng.agents.spec import AgentSpec
