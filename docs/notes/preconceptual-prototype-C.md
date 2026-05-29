# Approach C — Structural Skeleton

**Pattern under study:** (no name imposed)

Strip the code. Keep only the typed-edge structure: what kind of thing calls
what kind of thing, what flows where. If the pattern is real, the skeleton
should be identical across all five frameworks even though the surface code
looks different.

---

## The skeleton (common to all five exemplars)

```
[CALL_REQUEST]
    id: correlation_token
    name: tool_name
    args: serialized_args
        |
        | CALLS
        v
[TOOL_EXECUTOR]
        |
        | RETURNS
        v
[RESULT_ENVELOPE]
    content: serialized_result
    correlation_id: same token as CALL_REQUEST.id
    role_label: "tool" | ToolMessage | ToolReturnPart | ...
        |
        | APPENDED_TO
        v
[CONVERSATION_HISTORY]
        |
        | READ_BY
        v
[LLM_CALL_N+1]
```

The skeleton has four nodes and four typed edges. The `correlation_token`
field is the same string value on two separate nodes: `CALL_REQUEST` and
`RESULT_ENVELOPE`. That shared value is the only structural connection
between the two.

---

## How each framework instantiates the skeleton

### langgraph

```
CALL_REQUEST     = AIMessage.tool_calls[i]         (id = call["id"])
TOOL_EXECUTOR    = ToolNode._run_one(call, ...)
RESULT_ENVELOPE  = ToolMessage(content=..., tool_call_id=call["id"])
CONVERSATION     = state["messages"]  (list, append)
```

### ag2

```
CALL_REQUEST     = tool_call dict                  (id = tool_call.get("id"))
TOOL_EXECUTOR    = self.execute_function(call, call_id=tool_call_id)
RESULT_ENVELOPE  = {"role": "tool", "tool_call_id": tool_call_id, "content": content}
CONVERSATION     = messages list  (append)
```

### pydantic-ai

```
CALL_REQUEST     = ToolCallPart                    (tool_call_id = call.tool_call_id)
TOOL_EXECUTOR    = process_tool_calls(...)
RESULT_ENVELOPE  = ToolReturnPart(content=..., tool_call_id=call.tool_call_id)
                    wrapped in ModelRequest(parts=[...])
CONVERSATION     = ctx.state.message_history  (append)
```

Note: pydantic-ai adds an extra wrapper layer (`ModelRequest`) around
one or more `ToolReturnPart`s. The skeleton node `RESULT_ENVELOPE` maps
to the pair `(ToolReturnPart, ModelRequest)`, not to a single type.

### adk-python

```
CALL_REQUEST     = part.function_call              (id = part.function_call.id)
TOOL_EXECUTOR    = [framework routes via event system]
RESULT_ENVELOPE  = ChatCompletionToolMessage(role="tool",
                       tool_call_id=part.function_response.id,
                       content=response_content)
CONVERSATION     = tool_messages list  (append, then merged into request)
```

Note: adk-python uses `function_response.id` as the correlation token on
the result side, paired with `function_call.id` on the request side. These
are from different `Part` subtypes — the ID is still the same value.

### letta

```
CALL_REQUEST     = response_message.tool_calls[0]  (id = tool_call_id, may be overridden)
TOOL_EXECUTOR    = [dispatched by function_name]
RESULT_ENVELOPE  = Message.dict_to_message(openai_message_dict=response_message.model_dump(), ...)
CONVERSATION     = messages list  (append)
```

Note: letta may *generate* the correlation ID at this layer
(`get_tool_call_id()`) and backfill it into the request before appending.
The correlation invariant is preserved; the ID just doesn't always come from
the model.

---

## What varies across skeleton instantiations

- **Type name of RESULT_ENVELOPE**: 5 different names across 5 frameworks.
- **Type name of CALL_REQUEST**: 5 different names.
- **Whether RESULT_ENVELOPE is a top-level type or a sub-part**: varies.
- **Who generates the correlation token**: usually the LLM; letta may override.
- **Field name of the correlation token**: `tool_call_id` (4 frameworks) vs
  `function_response.id` (adk-python, internal layer).

## What does not vary

- The token appears on both sides.
- The token is a string.
- The result is appended to a list.
- The list is read by the next LLM call.
- The request and result are structurally separate entries in the list.

---

## The skeleton as a typed-edge graph (MetaCoding schema terms)

```
CALL_REQUEST   --[REFERENCES]--> correlation_token : str
RESULT_ENVELOPE --[REFERENCES]--> correlation_token : str   (same value)
RESULT_ENVELOPE --[REFERENCES]--> content : serialized_result
RESULT_ENVELOPE --[CONTAINED_IN]--> CONVERSATION
TOOL_EXECUTOR  --[RETURNS]--> RESULT_ENVELOPE
CALL_REQUEST   --[CALLS]--> TOOL_EXECUTOR
LLM_CALL_N1    --[REFERENCES]--> CONVERSATION
```

Seven typed edges. Three of them reference the same `correlation_token`
field — two direct refs (request side and result side) and one shared value.
This is the categorical invariant: the two ends of the call are **jointly
characterized by their relationship to a shared object** (the token). In
Yoneda terms, the token is the object through whose hom-set both
`CALL_REQUEST` and `RESULT_ENVELOPE` are determined to be correlated.

---

## What the skeleton does not capture

The skeleton erases:
- The *semantic* content of the tool result.
- The *timing* of execution (sync vs async).
- Whether the result can signal `result_as_answer` (crewAI-specific).
- Whether the framework batches multiple tool results per turn.
- Error handling paths (which often share the same skeleton but carry a
  status flag in the envelope).

These are local concerns. The skeleton is the shared structure.

---

*Does the skeleton make the pattern feel more precise or more drained of meaning? See the findings report.*
