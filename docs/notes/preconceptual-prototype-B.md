# Approach B — Contrast Pair: Where the Pattern Breaks

**Pattern under study:** (no name imposed)

The contrast pair is designed to force perception of the pattern boundary.
One exemplar fits the pattern clearly. The other *nearly* fits — it's also
about feeding tool output back into an agent loop — but it does something
structurally different. The goal: after reading both, you feel the edge.

---

## The strong exemplar — ag2 `conversable_agent.py`

```python
# autogen/agentchat/conversable_agent.py lines 2777–2805

tool_call_id = tool_call.get("id", None)

func = self._function_map.get(processed_call.get("name", None), None)
if is_coroutine_callable(func):
    coro = self.a_execute_function(processed_call, call_id=tool_call_id)
    _, func_return = self._run_async_in_thread(coro)
else:
    _, func_return = self.execute_function(processed_call, call_id=tool_call_id)

processed_return = self._process_tool_output(func_return)
content = processed_return.get("content", "")

if tool_call_id is not None:
    tool_call_response = {
        "tool_call_id": tool_call_id,   # <-- the ID threads through
        "role": "tool",                 # <-- typed as a distinct role
        "content": content,             # <-- result goes here
    }
```

What to notice:

- The `tool_call_id` is extracted from the *request*, passed to execution,
  and **re-attached to the result**. The same string appears on both sides.
- The result is stamped with `"role": "tool"` — it becomes a distinct
  message kind in the conversation.
- The conversation history will contain: `[assistant (with tool_calls)] →
  [tool (with tool_call_id matching)] → [next assistant]`.
  The two ends of the call are *correlated by the shared ID*.

---

## The near-miss — crewAI `agent_utils.py`

```python
# crewai/utilities/agent_utils.py lines 559–599

def handle_agent_action_core(
    formatted_answer: AgentAction,
    tool_result: ToolResult,
    messages: list[LLMMessage] | None = None,
    step_callback: Callable | None = None,
    show_logs: Callable | None = None,
) -> AgentAction | AgentFinish:

    if step_callback:
        cb_result = step_callback(tool_result)
        if inspect.iscoroutine(cb_result):
            asyncio.run(cb_result)

    formatted_answer.text += f"\nObservation: {tool_result.result}"  # <-- appended as text
    formatted_answer.result = tool_result.result

    if tool_result.result_as_answer:
        return AgentFinish(
            thought="",
            output=tool_result.result,
            text=formatted_answer.text,
        )

    if show_logs:
        show_logs(formatted_answer)

    return formatted_answer
```

What to notice:

- There is **no `tool_call_id`**. The result is not correlated to the
  request via a shared token. There is no token.
- The result is not a new message. It is **concatenated into the existing
  assistant message** as `"\nObservation: {tool_result.result}"`.
- The conversation history will contain: `[assistant (thought + action +
  observation, all as one text blob)]`. The tool result is invisible as a
  structural peer; it's a suffix on the prior message.
- `role: "tool"` never appears. There is no tool message kind.

---

## The structural difference

| Property | ag2 (strong exemplar) | crewAI (near-miss) |
|---|---|---|
| Shared correlation ID | yes — `tool_call_id` | no |
| Tool result as distinct message | yes — `role: "tool"` | no — appended text |
| Message list grows by one entry | yes | no |
| History remains parseable by conversation role | yes | only if you parse the text |
| LLM sees result as a message | yes | yes, but embedded in assistant turn |

---

## The boundary

Both do: execute a tool, feed the result back, loop.

Only the strong exemplar does: *wrap the result in a typed, correlated
envelope that is structurally separate from the request that caused it.*

The near-miss does the *functional* thing (feed result back) without the
*structural* thing (correlate + separate). This is not a deficiency — ReAct
style (crewAI) predates the tool_call / tool_result distinction and works
well. The pattern boundary is not "correct vs incorrect." It is: does the
framework treat the tool result as a **correlated reply** to a specific
request, or as **continuation text** in the assistant's stream?

---

## Why the near-miss is instructive

If you name the pattern "tool result injection," the near-miss seems to fit.
If you attend to the *correlation* and *role separation*, it clearly doesn't.
The name wants to refer to the functional act; the pattern refers to the
structural act. The contrast pair makes the structural criterion visible
without having to state it as a rule.

---

*Does forcing a yes/no judgment evoke "I see the shape"? See the findings report.*
