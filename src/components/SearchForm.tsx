import * as React from "react";
import { useState } from "react";
import { useLocation } from "react-router-dom";
import { parse } from "query-string";

// import "../styles/infoPanel.css";
import "../styles/SearchForm.css";
import SearchResults from "./SearchResults";

function SearchForm() {
  const location = useLocation();
  const urlQuery = parse(location.search).query as string;
  const [liveQuery, setLiveQuery] = useState(urlQuery);
  return (
    <div className="search-form">
      <form action="/search" method="get">
        <input
          type="text"
          name="query"
          id="query"
          value={liveQuery}
          onChange={(e) => setLiveQuery(e.target.value)}
        />
        <button type="submit">Search</button>
      </form>
      <SearchResults query={liveQuery} />
    </div>
  );
}
export default SearchForm;
