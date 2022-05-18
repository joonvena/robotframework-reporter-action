REPORT_PATH=$(pwd)/$REPORT_PATH

docker run \
  -e GH_ACCESS_TOKEN=$GH_ACCESS_TOKEN \
  -e REPO_OWNER=$REPOSITORY_OWNER \
  -e REPOSITORY=$REPOSITORY \
  -e COMMIT_SHA=$COMMIT_SHA \
  -e PR_ID=$PR_ID \
  -e REPORT_PATH="/reports" \
  -e SUMMARY=$SUMMARY \
  -e GITHUB_STEP_SUMMARY=$GITHUB_STEP_SUMMARY \
  -v $GITHUB_STEP_SUMMARY:/$GITHUB_STEP_SUMMARY:Z \
  -v $REPORT_PATH:/reports:Z \
  --user $(id -u):$(id -g) \
  joonvena/robot-reporter:v2.1
