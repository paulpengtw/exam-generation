## Purpose

Lets an operator stop all Fable model usage with one backend variable by substituting an Opus-class model at dispatch, while keeping requests successful and keeping an honest record of which model was requested and which model ran.

## ADDED Requirements

### Requirement: Operator switch
The system SHALL read a boolean backend variable `LLM_FABLE_DOWNGRADE`. The switch SHALL be enabled only when the value, trimmed and compared case-insensitively, is `1` or `true`. Any other value, an empty value, or an unset variable SHALL leave the switch disabled.

#### Scenario: Variable unset
- **WHEN** `LLM_FABLE_DOWNGRADE` is not set
- **THEN** the switch is disabled

#### Scenario: Variable set to an enabling value
- **WHEN** `LLM_FABLE_DOWNGRADE` is `1`, `true`, or `TRUE`
- **THEN** the switch is enabled

#### Scenario: Variable set to any other value
- **WHEN** `LLM_FABLE_DOWNGRADE` is `0`, `false`, `yes`, or an empty string
- **THEN** the switch is disabled

### Requirement: Fable calls run on the substitute model
While the switch is enabled, every LLM text call whose model id contains the substring `fable` SHALL be sent to the provider with the model id `claude-opus-4-6`. No provider request SHALL carry a model id containing `fable`. This SHALL hold for the plan, execute, verify, and correct tiers, the HTML figure call, the web-search fact-check call, the manual-review modification flow, the core-question planning endpoint, and the command-line entry points, whether the Fable id came from a per-request field or from a `LLM_MODEL_*` variable.

#### Scenario: Per-request Fable execute model
- **WHEN** the switch is enabled and a generation request sets `model_execute` to `claude-fable-5`
- **THEN** every execute-tier provider request for that run names `claude-opus-4-6`

#### Scenario: Fable configured by environment for the verify tier
- **WHEN** the switch is enabled, `LLM_MODEL_VERIFY` is `claude-fable-5`, and a question is verified
- **THEN** the verification provider request names `claude-opus-4-6`

#### Scenario: Web-search fact-check with a Fable verify model
- **WHEN** the switch is enabled, the effective verify model is a Fable model, and the Anthropic web-search fact-check runs
- **THEN** the fact-check provider request names `claude-opus-4-6`

#### Scenario: Other Fable ids
- **WHEN** the switch is enabled and a call's model id is `claude-fable-5-1` or `claude-fable-5-20250901`
- **THEN** the provider request names `claude-opus-4-6`

#### Scenario: Non-Fable model
- **WHEN** the switch is enabled and a call's model id is `claude-opus-5`, `claude-sonnet-5`, or `gemini-3.1-pro-preview`
- **THEN** the provider request names that same model id

### Requirement: Requests naming Fable still succeed
The switch SHALL NOT reject, hide, or remove Fable models. While the switch is enabled, the allowed-models list returned to clients SHALL be unchanged, and a request naming an allowed Fable model SHALL pass admission exactly as it does with the switch disabled.

#### Scenario: Model list unchanged
- **WHEN** the switch is enabled and a client requests the list of selectable models
- **THEN** the list contains the same entries, in the same order, as with the switch disabled

#### Scenario: Fable request admitted
- **WHEN** the switch is enabled and a generation request names `claude-fable-5` for any tier with an effort value that Fable accepts
- **THEN** the request is admitted and no HTTP 422 is returned on account of the model or the effort

### Requirement: Request options match the model that runs
When a call is substituted, the provider request options that depend on the model SHALL be those the system uses for `claude-opus-4-6`, not those for the requested Fable model. An effort value of `xhigh` SHALL be sent as `high`; the effort values `low`, `medium`, `high`, and `max` SHALL be sent unchanged.

#### Scenario: Output and thinking options
- **WHEN** a call is substituted
- **THEN** the provider request carries the same thinking and output-ceiling options as a call made directly to `claude-opus-4-6`

#### Scenario: Effort not accepted by the substitute
- **WHEN** a call with effort `xhigh` is substituted
- **THEN** the provider request carries effort `high`

#### Scenario: Effort accepted by the substitute
- **WHEN** a call with effort `max` is substituted
- **THEN** the provider request carries effort `max`

### Requirement: Records state the requested model and the model that ran
For every substituted call, the per-call exchange record SHALL identify `claude-opus-4-6` as the model used and SHALL also state the requested Fable model id. The stored parameters of a generation run SHALL keep the requested model values unchanged and SHALL additionally state, for each tier that was substituted, the requested model and the model that ran. The History detail view SHALL show both values for each substituted tier. Live stream events that name a call's model SHALL name the model that ran and SHALL also state the requested model. Regenerating from a History record SHALL submit the originally requested model values and SHALL NOT submit the substitution entry.

#### Scenario: Exchange record for a substituted call
- **WHEN** a substituted call completes and its exchange is recorded
- **THEN** the record's model-used value is `claude-opus-4-6` and the record also states the requested Fable model id

#### Scenario: Run parameters for a substituted tier
- **WHEN** a run that requested `claude-fable-5` for the execute tier is stored with the switch enabled
- **THEN** the stored parameters still show `claude-fable-5` as the requested execute model and additionally state that `claude-opus-4-6` ran for the execute tier

#### Scenario: History detail
- **WHEN** a user opens the History detail of a run with a substituted tier
- **THEN** the view shows, for that tier, the requested model and the model that ran

#### Scenario: Regenerate from a substituted record
- **WHEN** a user regenerates from a History record that has a substituted tier
- **THEN** the prefilled request names the originally requested Fable model for that tier and contains no substitution entry

#### Scenario: Run without substitution
- **WHEN** a run is stored in which no tier was substituted
- **THEN** its stored parameters and exchange records contain no substitution entry and History detail shows no substitution notice

### Requirement: Substitutions are logged
Each substituted call SHALL produce one log entry at WARNING level naming the requested model and the model that ran. The entry SHALL NOT contain prompt or response content.

#### Scenario: Log entry on substitution
- **WHEN** a call is substituted
- **THEN** one WARNING log entry names the requested model id and `claude-opus-4-6`, and contains no prompt or response text

### Requirement: Disabled switch changes nothing
While the switch is disabled, provider requests, stream events, exchange records, and stored run parameters SHALL be identical to those produced before this capability existed.

#### Scenario: Fable call with the switch disabled
- **WHEN** the switch is disabled and a call's model id is `claude-fable-5`
- **THEN** the provider request names `claude-fable-5` with the options the system uses for that model, and no substitution entry appears in any record or log
