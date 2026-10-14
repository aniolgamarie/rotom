# Model catalog and provider bindings

Catalog verification date: **2026-10-06**. This is a checked-in specification/pricing snapshot, not live availability. The pool lists optional models; roles determine which models are used. [OMP model presets](omp-model-presets.md) separately define role combinations, execution fallback chains, and permission-review choices.

`shared/model-templates.toml` centralizes model IDs, inputs, capacities, output budgets, and reasoning capabilities. `shared/models.toml` and `agents/omp/content.toml` bind templates to providers, protocol compatibility, and prices. Sharing a core specification across official OpenAI, official Anthropic, and TF bindings does not transfer gateway availability, plan entitlement, or billing guarantees.

## Official optional pool

Each tool selects eight official IDs from three API-key service providers. DSH/Pi default to OpenAI-compatible bindings; OMP defaults to Anthropic-compatible bindings. Other protocol definitions remain available for explicit selection. Unspecified main remains Kimi Code `kimi-for-coding`; explicit roles take precedence.

| Service | Provider IDs | Remote model ID | Context / client output budget | Configured inputs |
| --- | --- | --- | --- | --- |
| Kimi Code subscription | `kimi_code_openai` / `kimi_code_anthropic` | `kimi-for-coding` (K2.8 Preview) | 1048576 / 32768 | Text, image |
| Kimi Code subscription | Same | `k3` | 1048576 / 131072 | Text, image |
| Kimi Code subscription | Same | `k3-256k` | 262144 / 131072 | Text, image |
| Kimi Code subscription | Same | `kimi-for-coding-highspeed` | 262144 / 32768 | Text, image |
| GLM Coding Plan subscription | `glm_coding_openai` / `glm_coding_anthropic` | `glm-5.3` | 1000000 / 131072 | Text |
| GLM Coding Plan subscription | Same | `glm-5.3-flash` | 1000000 / 131072 | Text, image |
| Official metered DeepSeek API | `deepseek_openai` / `deepseek_anthropic` | `deepseek-flash` (V4.1 Flash) | 1048576 / 393216 | Text, image |
| Official metered DeepSeek API | Same | `deepseek-v4-pro` (V4 Pro 0813) | 1048576 / 393216 | Text |

Kimi IDs, membership requirements, and capabilities come from the [official model guide](https://www.kimi.com/code/docs/en/kimi-code/models.html). K3's 1M context requires a higher membership tier; use k3-256k or a verified account-specific context override where appropriate. K3/K2.8 Preview declare low/high/max; HighSpeed declares Thinking ON without invented effort levels. Output figures are the repository's fixed official OMP v18.4.5 SDK client budgets, not verified server maxima. Some service models support video, but these agent bindings declare text/image only.

Both GLM-5.3 variants belong to [Coding Plan](https://docs.z.ai/devpack/overview); the [Flash guide](https://docs.z.ai/guides/vlm/glm-5.3-flash) documents native images. Thinking cannot be disabled and low/high/max are declared. Pi disables off; OMP uses public `thinking.requiresEffort`. Context uses a conservative 1000000-token client budget. FlashX is a different route and is absent from this pool. International Z.AI and Chinese BigModel access constraints are not interchangeable; bindings retain the [Chinese Coding Plan endpoints](https://docs.bigmodel.cn/cn/coding-plan/tool/others). Video/files are outside the current agent input enum.

DeepSeek specifications follow the [official model catalog](https://api-docs.deepseek.com/api/list-models/). Pro remains a separate ID, subject to later [update notices](https://api-docs.deepseek.com/updates/); earlier assumptions that Pro routes to Flash are not reused after superseding announcements. Effort, tool-history, and tool-choice constraints follow the [thinking-mode guide](https://api-docs.deepseek.com/guides/thinking_mode/). Official prices retain the 2026-10-06 [pricing-page](https://api-docs.deepseek.com/quick_start/pricing/) snapshot; they are not copied to TF or represented as native support for currency/time-band pricing.

DSH currently projects capacities without the complete reasoning-mode constraints. Catalog capabilities do not mean every host can enforce every mode restriction. Hosts remain unmodified. See [known issues](known-issues.md) for current operational boundaries.

## Additional TF bindings

TF providers are enabled only by recipes selecting them. `omp-kernel` adds eleven bindings to the eight official defaults, for nineteen static selections:

| Provider | Protocol / address reference | Credential reference | Remote IDs |
| --- | --- | --- | --- |
| `kimi_tf` | OpenAI / `local:tf_openai_url` | `secret:omp_kimi_tf_key` | `kimi-for-coding`, `k3`, `k3-256k`, `kimi-for-coding-highspeed` |
| `zhipu_tf` | Anthropic / `local:tf_anthropic_url` | `secret:omp_zhipu_tf_key` | `glm-5.3`, `glm-5.3-flash`, `glm-5.2`, `glm-5.1`, `glm-5-turbo` |
| `deepseek_tf` | OpenAI / `local:tf_openai_url` | `secret:omp_deepseek_tf_key` | `deepseek-flash`, `deepseek-v4-pro` |

Three older GLM TF IDs remain separate candidates. Official-plan alias/upgrade behavior does not prove equivalent TF routing. Unverified multilevel reasoning mappings are not added to those old IDs. DeepSeek TF uses a separate key, entered through `model key deepseek_tf`; sharing a URL does not share a credential. Actual TF IDs, capabilities, routing, and billing have not been verified with real requests.

The official/OMP catalog contains eleven core templates and twenty-seven static bindings: sixteen official protocol bindings and eleven TF bindings. Its eleven providers comprise six official protocol endpoints, three TF endpoints, and two dynamic OAuth entries (Cursor/Codex). Dynamically discovered OAuth models are not static bindings. DSH separately supplies its tool-specific TF bindings as described in the [DSH guide](dsh.md).

```sh
./agentcfg model presets --verbose
./agentcfg --machine workstation --profile omp-kernel model status --verbose
```

The first command shows the public official pool; the second shows the selected recipe, missing values, and roles. Template expansion preserves adapter interfaces. Private machine model overrides retain their existing format and cannot declare templates. See [local configuration](local-config.md) for URLs/keys and [releases](releases.md) for version/evidence context.
