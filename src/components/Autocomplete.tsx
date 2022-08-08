import * as React from "react";
import { useState } from "react";

function AutocompleteInput({
  id,
  value,
  onChange,
}: {
  id?: string;
  value: string;
  onChange: React.ChangeEventHandler<HTMLInputElement>;
}) {
  const [isActive, setIsActive] = useState(false);
  return (
    <form className="autocomplete-input-container" autoComplete="off">
      <input
        {...{ id, value, onChange }}
        onFocus={(e) => setIsActive(true)}
        onBlur={(e) => setIsActive(false)}
      />
      {isActive ? <div>Autocomlete list</div> : null}
    </form>
  );
}

export default AutocompleteInput;
