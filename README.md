# Inventorius Frontend
An inventory management system for hobbyists and makers. This is the component that renders and serves the web app. Server-side and client-side api fetches are served by [inventorius-api].

# Reminder
Modified from [https://github.com/lob/generate-changelog#usage]
## Generate-Changelog Usage

To use this module, your commit messages have to be in this format:

```
type(category): description [flags]
```

Where `type` is one of the following:

* `breaking`
* `build`
* `ci`
* `chore`
* `docs`
* `feat`
* `fix`
* `other`
* `perf`
* `refactor`
* `revert`
* `style`
* `test`

Where `flags` is an optional comma-separated list of one or more of the following (must be surrounded in square brackets):

* `breaking`: alters `type` to be a breaking change

And `category` can be anything of your choice. If you use a type not found in the list (but it still follows the same format of the message), it'll be grouped under `other`.
