(function () {
  "use strict";

  var form = document.getElementById("claim-form");
  var input = document.getElementById("code");
  var issue = document.getElementById("issue");
  var message = document.getElementById("message");

  function say(text, ok) {
    message.textContent = text;
    message.className = ok ? "message ok" : "message";
  }

  function post(path, payload) {
    return fetch("/api/" + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {})
    }).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok) throw new Error(body.error || "服务暂不可用");
        return body;
      });
    });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var code = input.value.trim().toUpperCase();
    if (!/^ZY-?[2-9A-HJ-NP-Z]{4}-?[2-9A-HJ-NP-Z]{4}$/.test(code)) {
      say("恢复码形如 ZY-XXXX-XXXX，请检查后重试。");
      return;
    }
    var button = form.querySelector("button");
    button.disabled = true;
    say("");
    post("recovery/claim", { code: code })
      .then(function (body) {
        say("已恢复 " + body.projects.length + " 个项目，正在进入工作台。", true);
        location.href = "/";
      })
      .catch(function (error) {
        say(error.message);
        button.disabled = false;
      });
  });

  issue.addEventListener("click", function () {
    issue.disabled = true;
    say("");
    post("recovery")
      .then(function (body) {
        input.value = body.code;
        say("已生成，只显示这一次：" + body.code + "。请立即保存。", true);
      })
      .catch(function (error) {
        say(error.message + " 请先在工作台登记一个项目，再回到这里。");
      })
      .then(function () {
        issue.disabled = false;
      });
  });
})();
