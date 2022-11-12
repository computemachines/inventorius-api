import * as React from "react";
import { useState } from "react";

import "../styles/Autocomplete.css";

function AutocompleteList({
  selectedMatch,
  suggestions,
  onMakeSelection,
}: {
  selectedMatch: number;
  suggestions: string[];
  onMakeSelection: (selection: number) => void;
}) {
  return (
    <ul className="autocomplete__list">
      {suggestions.map((suggestion, index) => (
        <li
          onFocus={() => console.log("li focus")}
          key={index}
          onMouseDown={(e) => {
            console.log(e);
            onMakeSelection(index);
          }}
          className={`autocomplete__list-item ${
            index === selectedMatch ? "autocomplete__list-item--selected" : ""
          }`}
        >
          {suggestion}
        </li>
      ))}
    </ul>
  );
}

function clamp(v, min, max) {
  if (v === null) {
    return null;
  }
  if (v < min) {
    return min;
  }
  if (v > max) {
    return max;
  }
  return v;
}

function AutocompleteInput({
  id,
  value,
  setValue,
  className,
  suggestions,
}: {
  id?: string;
  value: string;
  setValue: (value: string) => void;
  className: string;
  suggestions: string[];
}) {
  const [isActive, setIsActive] = useState(false);
  const filteredSuggestions = suggestions.filter((suggestion) =>
    suggestion.toUpperCase().startsWith(value.toUpperCase())
  );
  const [selectedMatch, setSelectedMatch] = useState(null);
  return (
    <form
      className={`autocomplete ${className}`}
      onFocus={(e) => setIsActive(true)}
      onBlur={(e) => {
        setIsActive(false);
        setSelectedMatch(null);
      }}
      autoComplete="off"
    >
      <input
        {...{ id, value }}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          switch (e.key) {
          case "ArrowDown":
            if (selectedMatch === null) {
              console.log("init");
              setSelectedMatch(0);
            } else {
              console.log("down");
              setSelectedMatch(
                clamp(selectedMatch + 1, 0, filteredSuggestions.length - 1)
              );
            }
            break;
          case "ArrowUp":
            if (selectedMatch === null) {
              setSelectedMatch(filteredSuggestions.length - 1);
            } else {
              setSelectedMatch(
                clamp(selectedMatch - 1, 0, filteredSuggestions.length - 1)
              );
            }
            break;
          case "Tab":
            if (
              selectedMatch !== null &&
                selectedMatch >= 0 &&
                selectedMatch <= filteredSuggestions.length - 1
            ) {
              setSelectedMatch(null);
              setValue(filteredSuggestions[selectedMatch]);
            }
            break;
          default:
            break;
          }
        }}
      />
      {isActive ? (
        <AutocompleteList
          suggestions={filteredSuggestions}
          selectedMatch={selectedMatch}
          onMakeSelection={(i) => {
            setSelectedMatch(null);
            setValue(filteredSuggestions[i]);
          }}
        />
      ) : null}
    </form>
  );
}

export default AutocompleteInput;
