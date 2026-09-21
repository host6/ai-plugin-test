# implement an AI plugin that will force to create the correct header comment for new files

- URL: https://untill.atlassian.net/browse/AIR-4088
- ID: AIR-4088
- State: In Progress⚒️
- Author: Denis Gribanov
- Labels: none
- Assignees: Denis Gribanov
- Parent: AIR-2480

## Why

AI generates wrong header comment for new source code files

## What

If you’re creating a new file (list here) then the header comment must be:

```
/*
 * Copyright (c) <current year>-present unTill Software Development Group B.V.
 * @author <current git user name>
 */
```
