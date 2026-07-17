/** User-facing labels — hide engineering terminology in default UI. */

import type { DriveFileStatus } from "@/lib/api/types";

export const fileStatusLabel: Record<DriveFileStatus, string> = {
  discovered: "Found",
  indexing: "Preparing…",
  indexed: "Ready",
  failed: "Unavailable",
  skipped: "Not supported",
};

export const connectionStatusLabel = {
  checking: "Checking…",
  connected: "Drive connected",
  notConnected: "Not connected",
  error: "Connection error",
} as const;

export const knowledgeStatusLabel = {
  stale: "Your assistant may be out of date",
  update: "Update your assistant",
  /** Primary CTA label for the setup flow */
  prepare: "Set up your assistant",
  /** Sidebar chip action label */
  setup: "Set up my assistant",
  notReady: "Set up your assistant first",
  ready: "Your assistant is ready",
} as const;

export const prepareStepLabel = {
  connect: "Connected to Drive",
  scan: "Scanning your files",
  read: "Reading your documents",
  search: "Building search",
  ready: "Ready",
} as const;

export const prepareCopy = {
  title: "Set up your assistant",
  description:
    "Connect your Google Drive so DriveMind can answer questions with sources from your own files.",
  cta: "Set up my assistant",
  running: "Setting up your assistant…",
  complete: "Your assistant is ready",
  completeHint: "Ask your first question whenever you're ready.",
  durationHint: "This usually takes a few minutes.",
  advanced: "Advanced",
  lastPrepared: "Last set up",
  filesReady: "files ready",
} as const;

export const onboardingCopy = {
  welcomeTitle: "DriveMind AI",
  welcomeSubtitle: "Your personal knowledge OS",
  welcomeBody:
    "Ask anything about your Google Drive files and get answers with direct sources.",
  welcomeTrust: "Private · Read-only · Answers with sources",
  getStarted: "Get started",
  connectTitle: "Connect Google Drive",
  connectBody:
    "DriveMind reads your Drive so it can answer questions with sources. Your files stay read-only — we never write or delete anything.",
  connectCta: "Connect Google Drive",
  connectWaiting: "Connecting to Drive…",
  includeAll: "We'll include all your Google Drive files.",
  readyTitle: "Your assistant is ready",
  readyBody: "Try asking one of these to get started:",
  startChatting: "Start asking questions",
} as const;

export const filesCopy = {
  emptyTitle: "No files in your knowledge yet",
  emptyBody:
    "Set up your assistant to scan your Google Drive and make your documents searchable.",
  emptyCta: "Set up your assistant",
  notConnectedTitle: "Connect Google Drive",
  notConnectedBody: "Connect Drive to browse your knowledge library.",
  noResults: "No files match your search.",
  fileCount: "files in your knowledge",
  preview: "From this document",
  previewUnavailable:
    "Preview isn't available for this file type — you can still ask questions about it.",
  askAboutFile: "Ask about this file",
  openInDrive: "Open in Google Drive",
  details: "Details",
  modified: "Modified",
  folder: "Folder",
  type: "Type",
  searchPlaceholder: "Search your files…",
  pageTitle: "Your files",
  pageDescription: "Browse and explore your knowledge library.",
} as const;

export const fileFilterLabel: Record<DriveFileStatus | "all", string> = {
  all: "All",
  indexed: fileStatusLabel.indexed,
  indexing: fileStatusLabel.indexing,
  discovered: fileStatusLabel.discovered,
  failed: fileStatusLabel.failed,
  skipped: fileStatusLabel.skipped,
};

export const sourceCopy = {
  backToChat: "Back to conversation",
  excerpt: "Excerpt",
  askAboutDocument: "Ask about this document",
  openInDrive: "Open in Google Drive",
  moreDetails: "More details",
  modified: "Modified",
  fromDrive: "From your Google Drive",
  loadError: "Unable to load this source.",
  pageTitle: "Source",
  pageDescription: "Where this answer came from.",
} as const;

export const settingsCopy = {
  pageDescription: "Manage your account connection and appearance.",
  googleDrive: "Google Drive",
  appearance: "Appearance",
  about: "About",
  advanced: "Advanced",
  connect: "Connect Google Drive",
  reconnect: "Reconnect",
  disconnect: "Disconnect",
  disconnectHelp: "Opens Google Account permissions to revoke DriveMind access.",
  connectedAs: "Connected as",
  notConnected: "Connect Drive to search your documents and get answers with sources.",
  driveConnectedToast: "Google Drive connected",
  driveConnectedHint: "You're ready to set up your assistant and start asking questions.",
  driveErrorToast: "Could not connect Google Drive",
  aboutDescription: "Your personal AI knowledge assistant, powered by your Google Drive.",
  aboutVersion: "DriveMind AI",
} as const;

export const appCopy = {
  connectionBannerTitle: "Connect Google Drive",
  connectionBannerBody:
    "Connect your account to search your documents and get answers with sources.",
  connectionBannerCta: "Open Settings",
  connectionErrorTitle: "Unable to check connection",
  connectionErrorBody: "Make sure the app backend is running, then try again.",
} as const;

export const chatCopy = {
  brandName: "DriveMind AI",
  brandTagline: "Your personal knowledge OS",
  emptyHeading: "What would you like to know?",
  emptySubheading:
    "Ask anything from your Google Drive. I'll find the answer and show you exactly where it came from.",
  notReadyHeading: "Set up your assistant first",
  notReadyBody:
    "Connect your Google Drive and set up your assistant. It only takes a few minutes.",
  notReadyCta: "Set up my assistant",
  connectBody: "Connect Google Drive in Settings to get started.",
  recentChats: "Chats",
  noChatsYet: "No chats yet — click New Chat to start.",
  searchChatsPlaceholder: "Search chats…",
  noChatsMatch: "No chats match your search.",
  copyAnswer: "Copy",
  copied: "Copied",
  copiedToast: "Answer copied to clipboard",
  copyFailedToast: "Could not copy to clipboard",
  retry: "Try again",
  regenerate: "Regenerate",
  errorTitle: "Couldn't get an answer",
  followUpLabel: "Follow up",
  focusComposerHint: "focus",
  newChatHint: "new chat",
} as const;
