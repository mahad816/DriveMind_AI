export type ConversationRecord = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
};

export type ConversationGroup = {
  label: string;
  conversations: ConversationRecord[];
};
