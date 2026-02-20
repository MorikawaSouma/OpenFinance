import {
  BarChart3,
  BookOpen,
  Bot,
  Database,
  FileText,
  Gauge,
  Layers3,
  Settings,
  Shield,
  Workflow,
} from "lucide-react";
import { messages } from "@/lib/messages";

export const navItems = [
  { href: "/", label: messages.nav.dashboard, icon: Gauge },
  { href: "/chat", label: messages.nav.chat, icon: Bot },
  { href: "/pipeline", label: messages.nav.pipeline, icon: Workflow },
  { href: "/tasks", label: messages.nav.tasks, icon: Layers3 },
  { href: "/datasets", label: messages.nav.datasets, icon: Database },
  { href: "/strategies", label: messages.nav.strategies, icon: FileText },
  { href: "/factors", label: messages.nav.factors, icon: FileText },
  { href: "/reports", label: messages.nav.reports, icon: BarChart3 },
  { href: "/evidence", label: messages.nav.evidence, icon: BookOpen },
  { href: "/risk", label: messages.nav.risk, icon: Shield },
  { href: "/settings", label: messages.nav.settings, icon: Settings },
] as const;
