angular.module("surveyBuilder")
  .directive("questionSummary", function() {
    return {
      "restrict": "E",
      // need to add a fake variable to the end of the templateUrl to force the browser to reload the template
      "templateUrl": "/static/javascript/app/survey-builder/directives/question-summary/question-summary.html?n=1"
    };
  });
