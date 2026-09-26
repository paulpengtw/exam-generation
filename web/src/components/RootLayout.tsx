import { Outlet } from "react-router-dom";
import StagingBanner from "./StagingBanner";
import FeedbackButton from "./FeedbackButton";
import ReleaseNotice from "./ReleaseNotice";
import { useReleaseStatus } from "../lib/release/useReleaseStatus";
import { ActionFeedbackProvider } from "../motion/actionFeedback";

function ReleaseStatusMonitor() {
  useReleaseStatus();
  return null;
}

export default function RootLayout() {
  return (
    <ActionFeedbackProvider>
      <StagingBanner />
      <ReleaseStatusMonitor />
      <ReleaseNotice />
      <FeedbackButton />
      <Outlet />
    </ActionFeedbackProvider>
  );
}
