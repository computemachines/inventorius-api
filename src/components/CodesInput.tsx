import * as React from "react";

import "../styles/CodesInput.css";

import Cross from "./../img/lnr/CrossCircle";
import PlusCircle from "../img/lnr/PlusCircle";
import { ReactNode } from "react";

function BadgeRocker({
  state,
  setState,
}: {
  state: "owned" | "associated";
  setState: (newState: "owned" | "associated") => void;
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

export interface Code {
  value: string;
  kind: "owned" | "associated";
}
function CodesInput({
  id,
  codes,
  setCodes,
}: {
  id: string;
  codes: Code[];
  setCodes: (codes: Code[]) => void;
}) {
  // function specialKeyDownListener(e: React.KeyboardEventHandler<HTMLInputElement>) {

  // }

  return (
    <div>
      {codes.map((code, i) => (
        <CodeInput
          key={i}
          code={code}
          setCode={(code) => {
            let newCodes = [...codes];
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
                let newCodes = [...codes];
                newCodes.splice(i, 1);
                setCodes(newCodes);
              }}
            />
          ) : (
            <PlusCircle
              className="lnr-plus-circle"
              onClick={(e) =>
                setCodes([...codes, { value: "", kind: "owned" }])
              }
            />
          )}
        </CodeInput>
      ))}
    </div>
  );
}
export default CodesInput;
