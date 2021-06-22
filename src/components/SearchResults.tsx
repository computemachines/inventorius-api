import * as React from "react";
import { useEffect } from "react";
import { useHistory } from "react-router";
import { useFrontload } from "react-frontload";
import { FrontloadContext } from "../api-client/inventory-api";
import {
  BinState,
  isBatchState,
  isBinState,
  isSkuState,
  SearchResult,
  SearchResults as APISearchResults,
  SkuState,
} from "../api-client/data-models";

import "../styles/SearchResults.css";
import "../styles/infoPanel.css";
import { parse, stringifyUrl } from "query-string";
import DataTable, { HeaderSpec } from "./DataTable";
import { Pager } from "./Pager";

function resultToType(result: SearchResult): "SKU" | "BATCH" | "BIN" {
  if (isBinState(result)) return "BIN";
  if (isSkuState(result)) return "SKU";
  if (isBatchState(result)) return "BATCH";
}

function SearchResultsTable({
  searchResults,
  loading,
}: {
  searchResults: APISearchResults;
  loading?: boolean;
}) {
  const searchResultToDataRow = (result: SearchResult) => ({
    Identifier: result.id,
    Name: !isBinState(result) ? result.name : "",
    Type: resultToType(result),
  });
  const tabularData = searchResults.state.results.map(searchResultToDataRow);
  return (
    <DataTable
      headers={["Identifier", "Name", "Type"]}
      data={tabularData}
      headerSpecs={{
        Identifier: new HeaderSpec(".ItemLabel"),
        Name: new HeaderSpec(".truncated", {
          kind: "min-max-width",
          minWidth: 100,
          maxWidth: "1fr",
        }),
        // Quantity: new HeaderSpec(".numeric"),
      }}
      loading={loading}
    />
  );
}

function SearchResults({
  query,
  page,
  unsetPage,
  limit,
}: {
  query: string;
  page?: number;
  unsetPage?: () => void;
  limit?: number;
}) {
  page = page || 1;
  limit = limit || 20;

  const startingFrom = (page - 1) * limit;
  const { data, frontloadMeta, setData } = useFrontload(
    "searchresults-component",
    async ({ api }: FrontloadContext) => {
      console.log("frontload fetching");
      return {
        api: api,
        searchResults: await api.getSearchResults({
          query,
          startingFrom,
          limit,
        }),
      };
    }
  );
  const history = useHistory();
  const [isLoading, setIsLoading] = React.useState(false);

  // Update search results when query changes.
  // Do not update if not resolving most recent promise.
  useEffect(() => {
    if (!frontloadMeta.done) return;

    let isCancelled = false;
    setIsLoading(true);
    data.api
      .getSearchResults({ query, startingFrom, limit })
      .then((newSearchResults) => {
        if (!isCancelled) {
          setData(({ api }) => ({ api, searchResults: newSearchResults }));
          setIsLoading(false);
        }
      });
    return () => {
      isCancelled = true;
    };
  }, [query, startingFrom, limit]);

  useEffect(() => {
    if (unsetPage && page != 1) unsetPage();
  }, [query]);

  // save query to history if stay on page for 10s
  useEffect(() => {
    const urlParams = page == 1 ? { query } : { query, page };
    const timer = setTimeout(() => {
      history.push(stringifyUrl({ url: "/search", query: urlParams }));
    }, 10000);
    return () => clearTimeout(timer);
  });

  if (frontloadMeta.pending) return <div>Loading ...</div>;
  if (frontloadMeta.error || data.searchResults.kind == "problem")
    return <div>API error!</div>;

  const numPages = Math.ceil(
    data.searchResults.state.total_num_results / data.searchResults.state.limit
  );

  return (
    <div className="info-item">
      <div className="info-item-title">
        {data.searchResults.state.total_num_results} Results
      </div>
      <SearchResultsTable
        searchResults={data.searchResults}
        loading={isLoading}
      />
      <Pager
        currentPage={page}
        numPages={numPages}
        linkHref={stringifyUrl({ url: "/search", query: { query } }) + "&page="}
      />
    </div>
  );
}
export default SearchResults;
