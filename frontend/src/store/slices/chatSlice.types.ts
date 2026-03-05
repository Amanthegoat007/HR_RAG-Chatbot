export type BackendMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

export type BackendConversation = {
  id: string;
  title: string;
};
