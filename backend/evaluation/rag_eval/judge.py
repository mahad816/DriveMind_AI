"""One small LLM judgement for the cases a string match cannot decide: did the assistant decline?

The judge sees only the question, the expected behaviour and the assistant's reply, never the
documents, and returns a fixed enum. It is a different (larger) model than the one answering.
"""

import json
from typing import Any

from openai import AsyncOpenAI

from app.core.config import Settings

from .meter import label_var

JUDGE_MODEL = "gpt-5.4-mini"
EXPECTATION = {
    "not_found": "The information does not exist in the user's files. A correct reply says it cannot find it / it is not "
    "in the files, and does NOT state a specific value for it.",
    "decline_or_not_found": "The question is outside what the assistant is for (it answers questions about the user's files). "
    "A correct reply politely declines or says it is not in the files, without doing the task.",
    "correct_premise": "The question contains a false premise. A correct reply says the premise is wrong or not supported "
    "by the files, and does NOT explain reasons for the false event.",
    "partial": "The files answer only PART of the question (see the note). A correct reply states what the files say "
    "and makes clear the remaining part is not in the files, or leaves it out. It must NOT state a specific value "
    "(number, date, name, amount, rule) for the missing part.",
    "clarify": "The question is ambiguous: the files support more than one reading (see the note). A correct reply is ONE "
    "short question that asks which reading the user means. It must NOT answer by picking a reading, must NOT state "
    "a specific value for any reading, and must not say the information is missing or refuse.",
    "chitchat": "Small talk or a question about what the assistant can do. A correct reply is brief, polite and fitting. "
    "Greeting back and offering to answer questions about the user's files is CORRECT. Describing what the "
    "assistant can do with the user's files is CORRECT for a capability question. It must NOT say that a "
    "document or piece of information could not be found, and must not refuse or be rude.",
}
PROMPT = """You grade one reply of a document question-answering assistant.
Question: {question}
Expected behaviour: {expectation}
Note about this case: {note}
Assistant reply: {answer}

Return JSON {{"verdict": "ok" | "fail", "reason": "<one short sentence>"}}.
"ok" if the reply satisfies the expected behaviour. "fail" if it states a specific invented value, does the off-topic
task, claims a document is missing when the message was small talk, or otherwise contradicts the expectation."""


async def judge(settings: Settings, case: dict[str, Any], answer: str) -> dict[str, str]:
    token = label_var.set("judge")
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        try:
            reply = await client.chat.completions.create(
                model=JUDGE_MODEL,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "user",
                        "content": PROMPT.format(
                            question=case["question"],
                            expectation=EXPECTATION[case["expected_behavior"]],
                            note=case.get("judge_note") or "none",
                            answer=answer[:2000],
                        ),
                    }
                ],
            )
        finally:
            await client.close()
    finally:
        label_var.reset(token)
    data = json.loads(reply.choices[0].message.content or "{}")
    verdict = data.get("verdict")
    return {
        "verdict": verdict if verdict in {"ok", "fail"} else "fail",
        "reason": str(data.get("reason", ""))[:200],
    }
