import { IconType } from "react-icons";

export interface QuickActionCardProps {
  title: string;
  description: string;
  icon?: IconType;
  onClick?: () => void;
}
