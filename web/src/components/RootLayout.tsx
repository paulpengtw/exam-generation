import { Outlet } from "react-router-dom";
import StagingBanner from "./StagingBanner";
import FeedbackButton from "./FeedbackButton";
import ReleaseNotice from "./ReleaseNotice";
import { useReleaseStatus } from "../lib/release/useReleaseStatus";

function ReleaseStatusMonitor() {
  useReleaseStatus();
  return null;
}

export default function RootLayout() {
  return (
    <>
      <StagingBanner />
      <ReleaseStatusMonitor />
      <ReleaseNotice />
      <FeedbackButton />
      <Outlet />
    </>
  );
}
