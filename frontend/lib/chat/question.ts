import { questionCharacters } from "@/lib/demo";

export const QUESTION_LIMIT = 4000;
export const QUESTION_ERROR = "Enter a question of at most 4,000 characters.";

/** Shared by normal chat's composer, send handler and conversation controller. */
export function validQuestion(question: string): boolean {
  return !!question.trim() && questionCharacters(question) <= QUESTION_LIMIT;
}
