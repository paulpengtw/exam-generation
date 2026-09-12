import { ThemeProvider } from "next-themes";

import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/ui/sonner";
import { toast } from "sonner";

export function StackFitShadcnProbe() {
  return (
    <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false}>
      <Button type="button" onClick={() => toast.success("probe complete")}>
        Shadcn probe
      </Button>
      <Toaster />
    </ThemeProvider>
  );
}
