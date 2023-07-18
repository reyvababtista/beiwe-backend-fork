// Create an AngularJS module with a service and factory
angular.module("surveyBuilder")
  // Create a service to generate unique IDs (e.g., UUIDs)
  .service("uuid", function() {
    this.generate = function() {
      var d = new Date().getTime();
      return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
        var r = (d + Math.random() * 16) % 16 | 0;
        d = Math.floor(d / 16);
        return (c == "x" ? r : (r & 0x7 | 0x8)).toString(16);  // converts to hexadecimal?
      });
    }
  })
  
  // Create a factory to provide logic for generating new paths
  .factory("logicService", function() {
    return {
      getNewPath: getNewPath
    };
    
    /** Generate a new path based on the provided path, type, and optional index.*/
    function getNewPath(base_path, type, index) {
      var newPath = base_path + "/" + type;
      if (typeof index != "undefined") {
        newPath = newPath + "/" + index;
      }
      return newPath;
    }
  });
