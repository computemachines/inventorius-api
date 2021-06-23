import * as React from "react";

import "../styles/CodesInput.css";

import Cross from "./../img/search.svg";

type Code = string;
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
    <div className="flex-row">
      <Cross />
      {codes.map((code, i) => (
        <input
          id={i == codes.length - 1 ? id : null}
          type="text"
          value={code}
          onChange={(e) => {
            let newCodes = [...codes];
            newCodes[i] = e.target.value;
            setCodes(newCodes);
          }}
          onKeyDown={
            i == codes.length - 1
              ? (e) => {
                  if (e.key == "Tab" && code) {
                    let newCodes = [...codes];
                    newCodes.push("");
                    setCodes(newCodes);
                    console.log("Last tab");
                  }
                  if (e.key == "Backspace" || e.key == "Delete") {
                    console.log(e.key);
                  }
                }
              : null
          }
          key={i}
        />
      ))}
    </div>
  );
}
export default CodesInput;
