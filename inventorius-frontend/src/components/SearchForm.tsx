import * as React from "react";
import { useState } from "react";
import { useHistory, useLocation } from "react-router-dom";
import { parse, stringify } from "query-string";

// import "../styles/infoPanel.css";
import "../styles/SearchForm.css";
import SearchResults from "./SearchResults";

function SearchForm() {
  const location = useLocation();
  const history = useHistory();
  const urlQuery = parse(location.search).query as string;
  const page = parseInt(parse(location.search).page as string);
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
      <SearchResults
        query={liveQuery}
        page={page || 1}
        unsetPage={() => {
          history.push("/search?" + stringify({ urlQuery }));
        }}
      />
    </div>
  );
}
export default SearchForm;
