# OpenAI output-token limits and background mode for gpt-6.1-sol and gpt-6-luna

Study CD (session E6). Date checked for every item below: 2026-10-27.
Scope: OpenAI official pages only (developers.openai.com; `platform.openai.com/docs/...` 301-redirects there).

How the pages were read: the fetch tool returns a model-written summary of each page, not raw HTML. The quotes below are the
short exact strings it returned (it caps quotes at about 125 characters). Where a number or sentence matters, I fetched the
page more than once with different prompts and the answers agreed unless noted under "Conflicts".

## Answer in brief

| Question | gpt-6.1-sol | gpt-6-luna |
|---|---|---|
| Max output tokens | 128,000 | 128,000 |
| Context window | 1,050,000 | 1,050,000 |
| Max input tokens | 922,000 | 922,000 |
| Responses API (`v1/responses`) | Supported | Supported |
| Background mode listed on the model page | Not mentioned (no "background" string) | Not mentioned (no "background" string) |
| Background mode caps output differently | No such statement in any official page opened | No such statement in any official page opened |

The 128,000 cap is stated once per model and is not split by endpoint, so the same number covers both `max_output_tokens`
(Responses) and, by implication only, `max_completion_tokens` (Chat Completions). I could not open the Chat Completions
reference page (see Not found).

### OpenAI model page: GPT-6.1 Sol (OpenAI API docs, checked 2026-10-27)
- Link: https://developers.openai.com/api/docs/models/gpt-6.1-sol (old URL https://platform.openai.com/docs/models/gpt-6.1-sol returns 301 to it)
- What it does: model card for `gpt-6.1-sol` with limits, pricing, endpoints, features, snapshots, rate limits.
- Key numbers (quoted): "128,000 max output tokens"; "1,050,000 context window"; max input tokens 922,000 (the fetch tool gave this as a figure, not a quote); knowledge cutoff Apr 30, 2026. Endpoints table: "| Responses | `v1/responses` | Supported |". Also "Tool calling requires the Responses API." Features marked supported: streaming, structured_outputs, function_calling, file_search, image_input, web_search, prompt_caching. Not supported: fine_tuning, predicted_outputs. Single snapshot `gpt-6.1-sol`. Reasoning effort accepts low, medium (default), high, xhigh, max. Price per 1M text tokens: input $2, cached input $0.10, cache writes $2.50, output $10; prompts over 272K input tokens cost 2x input and 1.5x output for the whole request. Standard rate limits: Build 5,000 RPM / 1,000,000 TPM; Launch 10,000 RPM / 4,000,000 TPM; Grow 15,000 RPM / 40,000,000 TPM.
- Not on the page: the substring "background" (case-insensitive search, asked twice, same answer); whether reasoning tokens count toward the 128,000 (that is answered by the API reference below).
- Relevance to AutoAgentNetwork: cost and baseline limits. Worst-case spend for one call at the full cap is 128,000 x $10 / 1,000,000 = $1.28 (my arithmetic), which is 32% of the $4 single-run cap, so `aan estimate` must not assume the cap is never hit when reasoning effort is high.
- Resources: no code or data. Licence not applicable.
- Open questions it raises: whether background mode is supported is undocumented on this page (see Conflicts).

### OpenAI model page: GPT-6 Luna (OpenAI API docs, checked 2026-10-27)
- Link: https://developers.openai.com/api/docs/models/gpt-6-luna (old URL https://platform.openai.com/docs/models/gpt-6-luna returns 301 to it)
- What it does: model card for `gpt-6-luna`.
- Key numbers (quoted): "128,000 max output tokens"; "1,050,000 context window"; max input tokens 922,000; "May 18, 2026 knowledge cutoff". Endpoints: Responses `v1/responses` Supported (also Chat Completions and Batch). The page says "Use the Responses API for built-in tools and function calling." Features supported: same seven as Sol. Single snapshot `gpt-6-luna`. Price per 1M text tokens: input $0.10, cached input $0.01, cache writes $0.125, output $0.50. Default rate limits: Build 5,000 RPM / 2,000,000 TPM; Launch 10,000 RPM / 10,000,000 TPM; Grow 30,000 RPM / 180,000,000 TPM.
- Not on the page: the substring "background" (searched twice, same answer).
- Relevance to AutoAgentNetwork: cost and baseline limits. Worst-case spend for one call at the full cap is 128,000 x $0.50 / 1,000,000 = $0.064 (my arithmetic). The official price ($0.10 / $0.50) matches the figure quoted in `docs/RESEARCH_PROTOCOL.md` section 5, item 9 (line 134; booked at $0.20 / $1.20 in `configs/pricing.yaml`, about 2.4x official), so that protocol line is consistent with the page.
- Resources: none. Licence not applicable.
- Open questions it raises: same as Sol on background mode.

### OpenAI compare-models page (OpenAI API docs, checked 2026-10-27)
- Link: https://developers.openai.com/api/docs/models/compare?model=gpt-6.1-sol&model2=gpt-6-luna
- What it does: side-by-side table; it returned three columns (GPT-6.1 Sol, GPT-6 Luna, GPT-6 Astra).
- Key numbers (as returned): Max Output Tokens 128,000 for all three; Context Window 1,050,000 for all three; Supported Features row lists "Streaming, Function calling, Structured outputs, Image input" with no Background row (the fetch tool stated this explicitly).
- Relevance: confirms the two model pages and shows there is no per-model difference in output cap. Supports the "no background row" reading.
- Open questions: the Reasoning and Speed rows are visual and did not come through, so they are not recorded.

### OpenAI API reference: Create a model response (OpenAI API docs, checked 2026-10-27)
- Link: https://developers.openai.com/api/reference/resources/responses/methods/create (the page is about 511,000 characters; I read chunks starting at offsets 0, 100,000, 200,000, 300,000 and 400,000, not the last 11,000)
- What it does: request and response schema for `POST /v1/responses`.
- Key numbers (quoted):
  - `max_output_tokens`: "An upper bound for the number of tokens that can be generated for a response, including visible output tokens and [reasoning tokens](/api/docs/guides/reasoning)." No model-specific value and no separate background value appears in the chunks read.
  - `background`: "Whether to run the model response in the background."
  - `store`: "Whether to store the generated model response for later retrieval via API." and "Defaults to true when omitted."
  - `truncation`: `disabled` (default) fails with a 400 error if input exceeds the context window.
- Relevance: the 128,000 cap on the model pages therefore includes hidden reasoning tokens. Sets what `aan estimate` should treat as the worst case.
- Open questions: no stated minimum or maximum value for `max_output_tokens` in the chunks read, so the effective ceiling is the per-model figure above.

### OpenAI guide: Background mode (OpenAI API docs, checked 2026-10-27)
- Link: https://developers.openai.com/api/docs/guides/background
- What it does: describes asynchronous Responses runs started with `background: true`, polled with the GET endpoint until status leaves queued / in progress.
- Key numbers (quoted):
  - Enabling: "To start response generation in the background, make an API request with `background` set to `true`."
  - Models named: "Background mode enables you to execute long-running tasks on models like GPT-5.2 and GPT-5.2 Pro reliably," "without having to worry about timeouts or other connectivity issues." The code samples use `"model": "gpt-6-astra"`. Neither `gpt-6.1-sol` nor `gpt-6-luna` is named, and the page lists no unsupported models.
  - Limits section (three bullets): "Background requests can use `store=false`, but response data is temporarily" "stored to support asynchronous execution and polling."; "To cancel a synchronous response, terminate the connection"; "You can only start a new stream from a background response if you created it with `stream=true`."
  - Retention: ZDR projects run background requests with `store=false` and data is kept on disk "for roughly 10 minutes"; "Background responses are retained after the polling period only when `store=true` is explicitly provided."; "If `store` is omitted or set to `false` for a background request, the response is deleted after roughly 10 minutes."
  - No sentence contains "tokens" or "maximum" (searched), and the page ends after the Limits list.
- Relevance: the only official statement on background mode. It documents no output-token cap and no run-time cap, so there is no documented difference from synchronous requests. It also documents no per-model support list.
- Open questions it raises: this page predates or ignores the GPT-6 family (it names GPT-5.2), so silence is weak evidence either way. Support for the two models in background mode is undocumented, not documented as absent.

### OpenAI guide: Reasoning models (OpenAI API docs, checked 2026-10-27)
- Link: https://developers.openai.com/api/docs/guides/reasoning
- What it does: explains reasoning tokens and output budgeting.
- Key numbers (quoted): "you can limit the total number of tokens the model generates, including reasoning tokens, visible output tokens, and non-visible formatting tokens"; "OpenAI recommends reserving at least 25,000 tokens for reasoning and outputs when you start experimenting with these models."; on hitting the cap, "you'll receive a response with a `status` of `incomplete`" with `incomplete_details.reason` set to `max_output_tokens`; "This might occur before any visible output tokens are produced."
- Relevance: a run can be billed for output and still return no visible answer. The runner should treat `incomplete / max_output_tokens` as a failed item that still cost money.

### OpenAI guide: Using GPT-6 (OpenAI API docs, checked 2026-10-27)
- Link: https://developers.openai.com/api/docs/guides/latest-model
- Key numbers (quoted): "It supports `low`, `medium` (default), `high`, `xhigh`, and `max` reasoning effort." (Sol); "GPT-6 Sol and GPT-6 Luna support function calling in Chat Completions only with `reasoning_effort: "none"`." The page has nothing on background mode, `max_output_tokens`, long-running requests or timeouts (fetch tool reported "none" for each).
- Relevance: confirms the Responses API is the route for tools on these models. Not a source for any output limit.

## Conflicts

- A web search summary (not a page I opened) said the Sol model page "lists Background mode as a supported feature". Two direct fetches of that page and one of the compare page found no "background" string and no Background row. I treat background support as not documented on the model pages and do not rely on the search summary.

## Not found or not reachable

- Chat Completions reference (`max_completion_tokens`): https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create returned HTTP 404 on two fetches, although a search listed it. I have no quote from it. Do not state a separate `max_completion_tokens` limit; the model pages give one 128,000 figure.
- Any official page saying background mode does or does not support `gpt-6.1-sol` or `gpt-6-luna`: not found.
- Any official page saying background mode caps output differently: not found.
- A developer-forum thread (https://community.openai.com/t/why-is-gpt-6-1-sol-max-dramatically-slower-than-gpt-5-6-sol-max-using-the-same-prompt/1406429) appeared in search with a claim that a Sol run with effort max, started in background mode, hit a 1,800-second timeout. I did not open it, it is not an official source, and I record it only as a lead.

## So what (for `research/plan.md`)

1. Use 128,000 as the hard ceiling for `max_output_tokens` on both models, and remember it includes reasoning tokens. For worst-case cost, one call is at most $1.28 on Sol and $0.064 on Luna; `aan estimate` should price the cap, not the typical length, wherever effort is `high` or above.
2. Do not write down "background mode is supported" for Sol or Luna as a fact. The code path that sets `background` should be treated as relying on undocumented behaviour until a cheap fake-provider test plus one small live call shows it works; the live call goes through `aan` like any other paid run.
3. Do not assume background changes the output cap. Nothing official says it does, so keep `max_output_tokens` identical in foreground and background requests, and record the value in the cache key so runs stay comparable.
4. Set `store: true` explicitly on background requests. The docs say that for projects under Modified Abuse Monitoring a background response is kept past polling only when `store=true` is explicitly provided, otherwise it is deleted after about 10 minutes. Poll to completion inside that window or the result is lost.
5. Count `incomplete` with reason `max_output_tokens` as a billed failure, not a missing row, and reserve at least 25,000 tokens of budget for reasoning per the reasoning guide.
