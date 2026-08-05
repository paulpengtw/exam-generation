import type { GenerateParams } from "../api/generated/contract";
import type { FormParams } from "../components/ParamForm";

export function toGenerateParams(subject: string, params: FormParams): GenerateParams {
  const mathHasUserAuthoredPassage =
    subject === "math" && typeof params.passage === "string" && params.passage.trim() !== "";

  return {
    subject,
    grade: params.grade,
    style: subject === "math" && params.style ? [params.style] : [],
    content_type:
      subject === "social_studies" || subject === "math" || subject === "natural_sciences"
        ? params.content_type
        : undefined,
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
        ? (params.subject_filter ? [params.subject_filter] : undefined)
        : undefined,
    topic: params.topic,
    core_question: params.core_question,
    passage: params.passage,
    options: params.options,
    sub_context: subject === "natural_sciences" ? params.sub_context : undefined,
    science_competency: subject === "natural_sciences" ? params.science_competency : undefined,
    learning_performance: params.learning_performance,
    learning_content:
      subject === "social_studies" || subject === "natural_sciences"
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
    text_word_limit:
      (subject === "social_studies" || subject === "math" || subject === "natural_sciences") && !mathHasUserAuthoredPassage
        ? params.text_word_limit
        : undefined,
  };
}
