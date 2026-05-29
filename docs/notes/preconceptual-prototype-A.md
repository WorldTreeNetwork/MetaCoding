# Approach A — Side-by-Side: Tool Result Re-Injection

**Pattern under study:** (no name imposed)

Five agent frameworks each contain a moment where a tool's return value is
wrapped into a typed envelope, correlated back to the originating request via
a shared identifier, and deposited into the conversation history so the next
LLM call sees it as a peer message. The five slices below are that moment —
different syntax, different type systems, different names for the envelope.

---

## Structural axes to watch

Look across all five at once. Notice what stays constant and what varies.

| Axis | Varies or constant? |
|------|---------------------|
| The correlation token | constant — always a string ID linking request ↔ result |
| The role/type label on the result | varies — `"tool"`, `ToolMessage`, `ToolReturnPart`, `ChatCompletionToolMessage` |
| Where the result lands | nearly constant — appended to the conversation message list |
| The structural position of the ID | constant — present on both the request side and the result side |
| Whether the result is a first-class message or a sub-part | varies — some wrap results as top-level messages; pydantic-ai nests them as parts inside a `ModelRequest` |

---

## Exemplar 1 — langgraph `tool_node.py`

```python
# langgraph/libs/prebuilt/langgraph/prebuilt/tool_node.py ~line 807

ToolMessage(
    content=cached,
    tool_call_id=request.tool_call["id"],
)
```

And the error path, same shape:

```python
# ~line 1006
return ToolMessage(
    content=str(error),           # the result content
    tool_call_id=call["id"],      # correlator back to the request
    status="error",
)
```

The framework description (in the same file's docstring):

> *The "tools" node executes the tools (1 tool per tool_call) and adds the
> responses to the messages list as `ToolMessage` objects. The agent node
> then calls the language model again.*

---

## Exemplar 2 — ag2 / autogen `conversable_agent.py`

```python
# autogen/agentchat/conversable_agent.py ~line 2777

tool_call_id = tool_call.get("id", None)
func = self._function_map.get(processed_call.get("name", None), None)
_, func_return = self.execute_function(processed_call, call_id=tool_call_id)

content = processed_return.get("content", "")

if tool_call_id is not None:
    tool_call_response = {
        "tool_call_id": tool_call_id,   # correlator
        "role": "tool",                 # type label
        "content": content,             # the result
    }
```

The result is a plain dict (no typed class). The shape is identical to
Exemplar 1: a correlation ID plus a role label plus the content.

---

## Exemplar 3 — pydantic-ai `_agent_graph.py`

```python
# pydantic_ai/_agent_graph.py ~line 1307

part = _messages.ToolReturnPart(
    tool_name=call.tool_name,       # also named (unlike the others)
    content=message,                # the result
    tool_call_id=call.tool_call_id, # correlator
)
output_parts.append(part)
```

Then the parts are collected into a request and appended to history:

```python
# ~line 1217
if tool_responses:
    messages.append(
        _messages.ModelRequest(
            parts=tool_responses,           # wraps one or more ToolReturnParts
            run_id=ctx.state.run_id,
            timestamp=now_utc(),
        )
    )
```

The result is a *part* of a container message, not a standalone message.
The correlator is still present. The structural role is the same.

---

## Exemplar 4 — adk-python `lite_llm.py`

```python
# google/adk/models/lite_llm.py ~line 800

for part in content.parts:
    if part.function_response:
        response_content = (
            response
            if isinstance(response, str)
            else _safe_json_serialize(response)
        )
        tool_messages.append(
            ChatCompletionToolMessage(
                role="tool",                         # type label
                tool_call_id=part.function_response.id,  # correlator
                content=response_content,            # the result
            )
        )
```

The source is `part.function_response` — adk-python's internal type for a
function call result, converted here to the OpenAI-compatible wire format.
The output is `ChatCompletionToolMessage`, structurally identical to
Exemplars 1 and 2.

---

## Exemplar 5 — letta `agent.py`

```python
# letta/letta/agent.py ~line 478

if override_tool_call_id or response_message.function_call:
    tool_call_id = get_tool_call_id()   # generate fresh correlator
    response_message.tool_calls[0].id = tool_call_id
else:
    tool_call_id = response_message.tool_calls[0].id  # inherit correlator

# ... execute the function ...

messages.append(
    Message.dict_to_message(
        id=response_message_id,
        agent_id=self.agent_state.id,
        model=self.model,
        openai_message_dict=response_message.model_dump(),
        name=self.agent_state.name,
        group_id=group_id,
    )
)
```

Letta explicitly manages the correlation ID (it can even override it for
streaming compatibility). The final `messages.append(...)` is the injection
moment — the tool call request goes in first, then the result follows.

---

## The shape that emerges

Reading across all five columns:

```
[execute tool]
    → wrap result with correlation ID (= tool_call_id / function_response.id / ...)
    → label the wrapper with a role / type
    → append wrapper to the shared conversation history
    → [next LLM call sees the result as a peer message]
```

The shared ID is the structural invariant. It is present on the *request*
(the LLM's tool_call item) and on the *result* (the tool message). The two
ends of the call are threaded by it. Everything else — the type name, the
container structure, the exact append method — varies.

---

*Does this evoke "I see the shape"? See the findings report.*
