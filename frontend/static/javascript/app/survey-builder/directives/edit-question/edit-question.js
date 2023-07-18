angular.module("surveyBuilder")
  .directive("editQuestion", function() {
    return {
      link: link(),
      restrict: "E",
      scope: {
        show: "@?",
        surveyBuilder: "="
      },
      // need to add a fake variable to the end of the templateUrl to force the browser to reload the template
      templateUrl: "/static/javascript/app/survey-builder/directives/edit-question/edit-question.html?n=1"
    };
    
    ////////
    
    function link() {
      return function(scope) {
        if (scope.show) {
          // Default to showing the modal
          $('#editQuestionModal').modal("show");
        }
      }
    }
  });
