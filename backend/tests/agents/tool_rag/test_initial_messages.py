"""The first model call of every run is built in one place; its order and history note matter."""

from app.agents.tool_rag.agent_models import AgentMessage
from app.agents.tool_rag.agent_service import initial_messages
from app.agents.tool_rag.prompts import AGENT_SYSTEM_PROMPT
from app.agents.tool_rag.registry import ToolRegistry

PRIOR = (
    AgentMessage(role="USER", text="What is the meal limit?"),
    AgentMessage(role="ASSISTANT", text="40 USD per day."),
)


def test_policy_comes_first_and_the_question_last():
    messages = initial_messages("And for hotels?", PRIOR, history_window_complete=True)
    assert [m.role for m in messages] == ["SYSTEM", "SYSTEM", "USER", "ASSISTANT", "USER"]
    assert messages[0].text == AGENT_SYSTEM_PROMPT
    assert messages[-1].text == "And for hotels?"
    assert messages[2:4] == PRIOR


def test_the_history_note_says_whether_the_window_is_complete():
    complete = initial_messages("q", (), history_window_complete=True)[1].text or ""
    partial = initial_messages("q", (), history_window_complete=False)[1].text or ""
    assert "window is complete" in complete and "bounded recent history" not in complete
    assert "bounded recent history window" in partial and "is complete" not in partial


def test_without_a_history_flag_there_is_no_note():
    messages = initial_messages("q")
    assert [m.role for m in messages] == ["SYSTEM", "USER"]


def test_the_listing_tool_cannot_be_mistaken_for_a_way_to_read_documents():
    """A budget question once went to the file-listing tool half the time (KI-023)."""
    descriptions = {d["name"]: str(d["description"]) for d in ToolRegistry().definitions()}
    listing = descriptions["files_query"]
    assert "metadata" in listing and "cannot read document text" in listing
    assert "search_knowledge" in listing  # it names where content questions belong
    assert "text inside" in descriptions["search_knowledge"]
    assert all(len(text) <= 500 for text in descriptions.values())  # ToolDefinition's limit


def test_the_file_name_argument_says_a_document_number_is_not_a_file_name():
    """KI-025: "invoice INV-0457" was taken for a file name, looked up, not found, never searched.

    Measured with the real model: this wording cut those first calls from 25 of 70 to 2 of 70. Putting
    the same advice into the tool *description* also fixed them but stopped the model searching for a
    Roman-Urdu "not in the files" question (ru06: 17 of 20 searches became 0), so it is not there.
    """
    schema = next(d for d in ToolRegistry().definitions() if d["name"] == "resolve_file")
    reference = schema["parameters"]["properties"]["reference"]["description"]  # type: ignore[index]
    assert "Never a document number" in str(reference)
