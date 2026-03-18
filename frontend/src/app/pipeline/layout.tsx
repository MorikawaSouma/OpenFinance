import type { ReactNode } from "react";

import { PipelineWorkspaceProvider } from "@/components/providers/pipeline-workspace-provider";

export default function PipelineLayout({ children }: { children: ReactNode }) {
  return <PipelineWorkspaceProvider>{children}</PipelineWorkspaceProvider>;
}
