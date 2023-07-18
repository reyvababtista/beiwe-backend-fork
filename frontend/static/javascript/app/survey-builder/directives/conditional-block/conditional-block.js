angular.module("surveyBuilder")
  .directive("conditionalBlock", function(_, ARITHMETIC_OPERATORS) {
    return {
      link: function(scope) {
        scope._ = _;
        scope.ARITHMETIC_OPERATORS = ARITHMETIC_OPERATORS;
        scope.$watch("surveyBuilder.currentQuestionFields.question_id", function() {
          scope.currentQuestionId = scope.surveyBuilder.currentQuestionFields.question_id;
          scope.type = _.keys(scope.surveyBuilder.getValueAtPath(scope.path))[0];
        });
        scope.getQuestionNumber = function(questionId) {
          var index = _.indexOf(scope.surveyBuilder.questionIds, questionId);
          if (index >= 0) {
            return "Q" + ++index;
          } else {
            return "(error)"
          }
        }
      },
      replace: true,
      restrict: "E",
      scope: {
        surveyBuilder: "=",
        path: "@"
      },
      // need to add a fake variable to the end of the templateUrl to force the browser to reload the template
      templateUrl: "/static/javascript/app/survey-builder/directives/conditional-block/conditional-block.html?n=1"
    };
  });
