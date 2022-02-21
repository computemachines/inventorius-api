import * as React from "react";

import "../styles/CodesInput.css";

import Cross from "./../img/lnr/CrossCircle";
import PlusCircle from "../img/lnr/PlusCircle";
import { ReactNode } from "react";

function BadgeRocker({
  state,
  setState,
  editable = true,
}: {
  state: "owned" | "associated";
  setState?: (newState: "owned" | "associated") => void;
  editable?: boolean;
}) {
  return (
    <div className="badge-rocker">
      <button
        tabIndex={-1}
        type="button"
        className={state == "owned" ? "rocker--active" : ""}
        onClick={(e) => setState("owned")}
      >
        Owned
      </button>
      <button
        tabIndex={-1}
        type="button"
        className={state == "associated" ? "rocker--active" : ""}
        onClick={(e) => setState("associated")}
      >
        Associated
      </button>
    </div>
  );
}

function CodeInput({
  id,
  code,
  setCode,
  onKeyDown,
  children,
}: {
  id?: string;
  code: Code;
  setCode: (code: Code) => void;
  onKeyDown?: React.KeyboardEventHandler<HTMLInputElement>;
  children?: ReactNode;
}) {
  return (
    <div className="codes-input-line ">
      <input
        id={id}
        type="text"
        value={code.value}
        onChange={(e) => {
          setCode({ ...code, value: e.target.value });
        }}
        onKeyDown={onKeyDown}
      />
      <BadgeRocker
        state={code.kind}
        setState={(state) => setCode({ ...code, kind: state })}
      />
      {children}
    </div>
  );
}

function CodeLine({ code }: { code: Code }) {
  return (
    <div className="code-line">
      <div className="code-line-code">{code.value}</div>
      <div className="badge">
        {code.kind == "owned" ? "Owned" : "Associated"}
      </div>
    </div>
  );
}

export interface Code {
  value: string;
  kind: "owned" | "associated";
  inherited?: boolean;
}
function CodesInput({
  id,
  codes,
  editable = true,
  setCodes,
}: {
  id?: string;
  codes: Code[];
  editable?: boolean;
  setCodes?: (codes: Code[]) => void;
}) {
  function editableCodeLine(code, i, codes) {
    const isLast = i + 1 == codes.length;
    return (
      <CodeInput
        key={i}
        code={code}
        setCode={(code) => {
          const newCodes = [...codes];
          newCodes[i] = code;
          setCodes(newCodes);
        }}
        onKeyDown={
          i == codes.length - 1
            ? (e) => {
              if (e.key == "Tab" && code.value) {
                setCodes([...codes, { value: "", kind: "owned" }]);
              }
            }
            : null
        }
      >
        {i < codes.length - 1 ? (
          <Cross
            className="lnr-cross-circle"
            onClick={(e) => {
              const newCodes = [...codes];
              newCodes.splice(i, 1);
              setCodes(newCodes);
            }}
          />
        ) : (
          <PlusCircle
            className="lnr-plus-circle"
            onClick={(e) => setCodes([...codes, { value: "", kind: "owned" }])}
          />
        )}
      </CodeInput>
    );
  }
  const defaultCode: Code = { kind: "owned", value: "" };
  if (editable) {
    return (
      <div className="code-lines">
        {(codes.length == 0 ? [defaultCode] : codes).map(editableCodeLine)}
      </div>
    );
  } else {
    return (
      <div className="code-lines">
        {codes.map((code, i) => (
          <CodeLine key={i} code={code} />
        ))}
      </div>
    );
  }
}
export default CodesInput;
