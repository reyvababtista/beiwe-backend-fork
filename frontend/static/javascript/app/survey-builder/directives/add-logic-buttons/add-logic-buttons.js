angular.module("surveyBuilder")
  .directive("addLogicButtons", function() {
    return {
      "restrict": "E",
      "scope": {
        "surveyBuilder": "=",
        "newPath": "@"
      },
      // need to add a fake variable to the end of the templateUrl to force the browser to reload the template
      "templateUrl": "/static/javascript/app/survey-builder/directives/add-logic-buttons/add-logic-buttons.html?n=1"
    };
  });
