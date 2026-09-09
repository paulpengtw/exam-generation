import type { GenerateParams } from "../api/generated/contract";
import type { FormParams } from "../components/ParamForm";

export function toGenerateParams(subject: string, params: FormParams): GenerateParams {
  const mathHasUserAuthoredPassage =
    subject === "math" && typeof params.passage === "string" && params.passage.trim() !== "";
  const styles = Array.isArray(params.style)
    ? params.style
    : params.style
      ? [params.style]
      : [];
  const subjectFilters = Array.isArray(params.subject_filter)
    ? params.subject_filter
    : params.subject_filter
      ? [params.subject_filter]
      : [];

  return {
    subject,
    grade: params.grade,
    style: subject === "math" ? styles : [],
    content_type:
      subject === "social_studies" || subject === "math" || subject === "natural_sciences"
        ? params.content_type
        : undefined,
    ...(subject === "social_studies" && params.content_domain
      ? { content_domain: params.content_domain }
      : {}),
    ...(subject === "social_studies" && params.target_surface === "數位"
      ? { target_surface: "數位" as const }
      : {}),
    context: subject === "math" || subject === "natural_sciences" ? params.context : [],
    set_type: params.set_type,
    q_type: params.q_type,
    count: params.count,
    skip_verify: params.skip_verify,
    disable_reference_fewshot:
      subject === "social_studies" || subject === "natural_sciences"
        ? params.disable_reference_fewshot
        : undefined,
    image_generation_mode:
      subject === "social_studies" || subject === "math" || subject === "natural_sciences"
        ? params.image_generation_mode
        : undefined,
    subject_filter:
      subject === "social_studies" || subject === "math"
        ? (subjectFilters.length ? subjectFilters : undefined)
        : undefined,
    core_competency:
      subject === "math" || subject === "social_studies"
        ? params.core_competency
        : undefined,
    math_thinking: subject === "math" ? params.math_thinking : undefined,
    topic: params.topic,
    core_question: params.core_question,
    text_instruction: (subject === "social_studies" || subject === "natural_sciences") ? params.text_instruction : undefined,
    passage: params.passage,
    options: params.options,
    sub_context: subject === "natural_sciences" ? params.sub_context : undefined,
    science_competency: subject === "natural_sciences" ? params.science_competency : undefined,
    learning_performance: params.learning_performance,
    learning_content:
      subject === "social_studies" || subject === "math" || subject === "natural_sciences"
        ? params.learning_content
        : undefined,
    sub_question_count:
      subject === "social_studies" || subject === "math" || subject === "natural_sciences"
        ? params.sub_question_count
        : undefined,
    subquestion_configs:
      subject === "social_studies" || subject === "natural_sciences"
        ? params.subquestion_configs
        : undefined,
    per_question_params: params.per_question_params,
    drawn: params.drawn,
    seed: params.seed,
    model_plan: params.model_plan,
    model_execute: params.model_execute,
    model_verify: params.model_verify,
    model_correct: params.model_correct,
    effort_plan: params.effort_plan,
    effort_execute: params.effort_execute,
    effort_verify: params.effort_verify,
    effort_correct: params.effort_correct,
    difficulty: subject !== "natural_sciences" ? params.difficulty : undefined,
    reporting_scale: subject === "natural_sciences" ? params.reporting_scale : undefined,
    coverage_mode: subject === "social_studies" ? params.coverage_mode : undefined,
    ...(subject === "social_studies" || subject === "natural_sciences"
      ? { core_question_callback: params.core_question_callback }
      : {}),
    text_word_limit:
      (subject === "social_studies" || subject === "math" || subject === "natural_sciences") && !mathHasUserAuthoredPassage
        ? params.text_word_limit
        : undefined,
  };
}
