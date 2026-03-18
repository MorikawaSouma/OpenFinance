import type { ReactNode } from "react";

import { ChatWorkspaceProvider } from "@/components/providers/chat-workspace-provider";

export default function ChatLayout({ children }: { children: ReactNode }) {
  return <ChatWorkspaceProvider>{children}</ChatWorkspaceProvider>;
}
