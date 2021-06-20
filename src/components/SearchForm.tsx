import * as React from "react";

// import "../styles/infoPanel.css";
import "../styles/SearchForm.css";
import SearchResults from "./SearchResults";

function SearchForm() {
  return (
    <div className="search-form">
      <form action="/search" method="get">
        <input type="text" name="query" id="query" />
        <button type="submit">Search</button>
      </form>
      <SearchResults />
    </div>
  );
}
export default SearchForm;
