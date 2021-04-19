# Robot Framework Reporter Action

This action creates parsed report about the test run and sends it as comment to that specific commit that triggered the action.  

![Example](example.png)  

## Example usage


```jobs:
   generate_report:
        runs-on: ubuntu-latest
        - name: Get Repository Owner & Name
          run: |
            export OWNER="$(echo "${{ github.repository }}" | awk -F / '{print $1}' | sed -e "s/:refs//")"
            export REPO="$(echo "${{ github.repository }}" | awk -F / '{print $2}' | sed -e "s/:refs//")"
            echo "REPOSITORY_OWNER=$OWNER" >> $GITHUB_ENV
            echo "REPOSITORY_NAME=$REPO" >> $GITHUB_ENV
        - name: Send report to commit
          uses: joonvena/robotframework-reporter-action@v0.1
          env:
            GH_ACCESS_TOKEN: ${{ secrets.TOKEN }}
            REPO_OWNER: ${{ env.REPOSITORY_OWNER }}
            COMMIT_SHA: ${{ github.sha }}
            REPOSITORY: ${{ env.REPOSITORY_NAME }}
            REPORT_PATH: ${{ github.workspace }}/reports
```

Get repository Owner & Name step is not needed you can define these as secrets also if you like.

`GH_ACCESS_TOKEN`
Token to access github api

`REPO_OWNER`
Owner of the repository

`COMMIT_SHA`
SHA of commit that triggered the action

`REPOSITORY`
Repository name

`REPORT_PATH`
Path where the report output is
