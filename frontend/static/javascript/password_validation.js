// based on https://www.w3schools.com/howto/howto_js_password_validation.asp
window.addEventListener('load', function () {
  var password_1 = document.getElementById("new_password")
  var password_2 = document.getElementById("confirm_new_password")
  var letter = document.getElementById("letter")
  var capital = document.getElementById("capital")
  var number = document.getElementById("number")
  var special = document.getElementById("special")
  var length = document.getElementById("length")
  var match = document.getElementById("match")
  var button = document.getElementById("change_password_button")
  
  // run validation whenever the password field changes (works with paste)
  password_1.onkeyup = function() {
    // Validate lowercase letters
    var lowerCaseLetters = /[a-z]/g
    if (password_1.value.match(lowerCaseLetters)) {
      letter.classList.remove("invalid")
      letter.classList.add("valid")
    } else {
      letter.classList.remove("valid")
      letter.classList.add("invalid")
    }

    // Validate capital letters
    var upperCaseLetters = /[A-Z]/g
    if (password_1.value.match(upperCaseLetters)) {
      capital.classList.remove("invalid")
      capital.classList.add("valid")
    } else {
      capital.classList.remove("valid")
      capital.classList.add("invalid")
    }

    // Validate numbers
    var numbers = /[0-9]/g
    if (password_1.value.match(numbers)) {
      number.classList.remove("invalid")
      number.classList.add("valid")
    } else {
      number.classList.remove("valid")
      number.classList.add("invalid")
    }

    // Validate special_characters
    var specials = /[^0-9a-zA-Z]/g
    if (password_1.value.match(specials)) {
      special.classList.remove("invalid")
      special.classList.add("valid")
    } else {
      special.classList.remove("valid")
      special.classList.add("invalid")
    }

    // Validate length
    if (password_1.value.length >= window.min_password_length) {
      length.classList.remove("invalid")
      length.classList.add("valid")
    } else {
      length.classList.remove("valid")
      length.classList.add("invalid")
    }
  }
  
  // password match field must match
  password_2.onkeyup = function () {
    // test that the passwords match and the minimum length in order to avoid glitches
    if (password_1.value == password_2.value & password_1.value.length >= window.min_password_length) {
      match.classList.remove("invalid")
      match.classList.add("valid")
      button.disabled = undefined
    } else {
      match.classList.remove("valid")
      match.classList.add("invalid")
      button.disabled = true
    }
  }
})
