import MotionRoot from "../motion/MotionRoot";
import { Outlet } from "react-router-dom";
import StagingBanner from "./StagingBanner";
import FeedbackButton from "./FeedbackButton";

export default function RootLayout() {
  return (
    <MotionRoot>
      <StagingBanner />
      <FeedbackButton />
      <Outlet />
    </MotionRoot>
  );
}
