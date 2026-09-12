import { ApprovalCard } from "@aicss/react/approval-card";
import { Orb } from "@aicss/react/orbs";
import { StreamingText } from "@aicss/react/streaming-text";
import { TextResponse } from "@aicss/react/text-response";
import { ThinkingReasoning } from "@aicss/react/thinking-reasoning";
import { ThinkingState } from "@aicss/react/thinking-state";
import { TodoList } from "@aicss/react/task-list";
import { mountStackFitProbe } from "../src/research/StackFitBuildShell";

mountStackFitProbe(
  <>
    <ThinkingState />
    <ThinkingReasoning />
    <Orb label="Orb probe" pill />
    <StreamingText text="stream" />
    <TodoList />
    <ApprovalCard variant="command" command="echo probe" />
    <TextResponse>response</TextResponse>
  </>,
);
