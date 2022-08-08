import * as React from "react";
import { ReactNode } from "react";

import "../styles/Toast.css";

export type SetToastContent = ({
  content,
  mode,
}: {
  content?: ReactNode;
  mode?: "success" | "failure";
}) => void;

export const ToastContext =
  React.createContext<{ setToastContent: SetToastContent }>(null);

// render toast component
// Is rendered as closed/inactive when children is falsy
export const Toast = ({
  onClose,
  children,
  mode,
}: {
  onClose: () => void;
  children?: ReactNode;
  mode?: "success" | "failure";
}) =>
  children ? (
    <div className={`toast ${mode ? mode : ""}`} id="#toast">
      <button role="close" className="toast__close-button" onClick={onClose}>
        X
      </button>
      {children}
    </div>
  ) : null;
