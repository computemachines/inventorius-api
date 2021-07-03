import * as React from "react";
import { ReactNode } from "react";

import "../styles/Alert.css";

type SetAlertContent = ({
  content,
  mode,
}: {
  content?: ReactNode;
  mode?: "success" | "failure";
}) => void;

export const AlertContext =
  React.createContext<{ setAlertContent: SetAlertContent }>(null);

export const Alert = ({
  onClose,
  children,
  mode,
}: {
  onClose: () => void;
  children?: ReactNode;
  mode?: "success" | "failure";
}) =>
  children ? (
    <div className={`main-alert ${mode ? mode : ""}`} id="#alert">
      <button role="close" className="alert-close-button" onClick={onClose}>
        X
      </button>
      {children}
    </div>
  ) : null;
