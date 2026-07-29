import { Outlet } from "react-router-dom";
import StagingBanner from "./StagingBanner";
import FeedbackButton from "./FeedbackButton";

export default function RootLayout() {
  return (
    <>
      <StagingBanner />
      <FeedbackButton />
      <Outlet />
    </>
  );
}
