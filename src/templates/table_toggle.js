/* 表ごとの表示 ON/OFF。ページの中に埋め込んで使う（外部のファイルは読み込まない）。

   ・隠した表の名前を、見ている人のブラウザのローカルストレージに保存する。サーバーには何も送らない
   ・保存するのは「隠した表」の名前だけ。だから新しく増えた表は、最初は表示される
   ・ローカルストレージが使えない・中身が読めないときは、エラーにせず全部表示で動く
   ・表は名前（data-table）で見分ける。名前が同じなら、別の回のページでも同じ表が隠れる */
(function () {
  "use strict";

  // 同じドメインの別のアプリと設定が混ざらないよう、名前は websitemaker で始める。
  var STORAGE_KEY = "websitemaker.hiddenTables";

  // 保存された文字列から、隠す表の名前の一覧を取り出す。読めなければ空（＝全部表示）。
  function parseHidden(raw) {
    var value;
    if (!raw) {
      return [];
    }
    try {
      value = JSON.parse(raw);
    } catch (e) {
      return [];
    }
    if (!Array.isArray(value)) {
      return [];
    }
    var names = [];
    for (var i = 0; i < value.length; i++) {
      if (typeof value[i] === "string" && names.indexOf(value[i]) < 0) {
        names.push(value[i]);
      }
    }
    return names;
  }

  // 2列の枠の中身を、出すかどうかの並びにする。
  // items は枠の中身を上から順に { spacer: 空き枠か, hidden: 隠した表か } で並べたもの。
  //
  // 「（空き）」は、右列を空けて次の表を左列から始めるための枠。表を隠して並びが詰まると、
  // 空き枠が左列に来たり、後ろに表が無くなったりして、ただの余白になる。そこで:
  //   ・何も隠していなければ、空き枠は今までどおり全部出す（display_order.txt のとおり）
  //   ・何か隠していれば、右列に来て、かつ後ろに表が残っている空き枠だけを出す
  function layoutItems(items) {
    var anyHidden = false;
    var i;
    for (i = 0; i < items.length; i++) {
      if (!items[i].spacer && items[i].hidden) {
        anyHidden = true;
      }
    }

    var shown = [];
    var position = 0; // 出す枠の数。偶数なら次は左列、奇数なら右列
    for (i = 0; i < items.length; i++) {
      var keep;
      if (!items[i].spacer) {
        keep = !items[i].hidden;
      } else if (!anyHidden) {
        keep = true;
      } else {
        keep = position % 2 === 1 && hasShownTableAfter(items, i);
      }
      shown.push(keep);
      if (keep) {
        position++;
      }
    }
    return shown;
  }

  function hasShownTableAfter(items, index) {
    for (var i = index + 1; i < items.length; i++) {
      if (!items[i].spacer && !items[i].hidden) {
        return true;
      }
    }
    return false;
  }

  // このページにある表のうち、隠している表の数（ほかの回にしか無い名前は数えない）。
  function countHidden(hidden, namesOnPage) {
    var count = 0;
    for (var i = 0; i < namesOnPage.length; i++) {
      if (hidden.indexOf(namesOnPage[i]) >= 0) {
        count++;
      }
    }
    return count;
  }

  function hiddenMessage(count) {
    return count > 0 ? count + "個のニュース項目を非表示中" : "";
  }

  // ---- ここから下はブラウザの中でだけ動く ----

  function openStorage() {
    try {
      return window.localStorage || null;
    } catch (e) {
      // 設定で保存を禁止しているブラウザでは、触るだけで例外になる。
      return null;
    }
  }

  function loadHidden(storage) {
    if (!storage) {
      return [];
    }
    try {
      return parseHidden(storage.getItem(STORAGE_KEY));
    } catch (e) {
      return [];
    }
  }

  // 保存できたら true。できなくても画面の切り替えはそのまま続ける。
  function saveHidden(storage, hidden) {
    if (!storage) {
      return false;
    }
    try {
      if (hidden.length === 0) {
        storage.removeItem(STORAGE_KEY);
      } else {
        storage.setItem(STORAGE_KEY, JSON.stringify(hidden));
      }
      return true;
    } catch (e) {
      return false;
    }
  }

  function each(list, fn) {
    Array.prototype.forEach.call(list, fn);
  }

  function init() {
    var panel = document.getElementById("table-toggle");
    if (!panel) {
      return;
    }
    var storage = openStorage();
    var hidden = loadHidden(storage);
    var targets = document.querySelectorAll("[data-table]");
    var boxes = panel.querySelectorAll("input[type=checkbox]");
    var countLabel = panel.querySelector("[data-toggle-count]");
    var unsavedNote = panel.querySelector("[data-toggle-unsaved]");

    var namesOnPage = [];
    each(boxes, function (box) {
      namesOnPage.push(box.value);
    });

    function isHidden(name) {
      return hidden.indexOf(name) >= 0;
    }

    function apply() {
      each(targets, function (el) {
        el.hidden = isHidden(el.getAttribute("data-table"));
      });

      each(document.querySelectorAll(".grid"), function (grid) {
        var children = grid.children;
        var items = [];
        each(children, function (el) {
          var spacer = el.classList.contains("spacer");
          items.push({ spacer: spacer, hidden: !spacer && el.hidden });
        });
        var shown = layoutItems(items);
        each(children, function (el, i) {
          el.hidden = !shown[i];
        });
      });

      // 枠の表がすべて隠れたら、枠の見出しごと消す。
      each(document.querySelectorAll(".table-group"), function (group) {
        var tables = group.querySelectorAll("[data-table]");
        var visible = 0;
        each(tables, function (el) {
          if (!el.hidden) {
            visible++;
          }
        });
        group.hidden = tables.length > 0 && visible === 0;
      });

      each(boxes, function (box) {
        box.checked = !isHidden(box.value);
      });
      if (countLabel) {
        countLabel.textContent = hiddenMessage(countHidden(hidden, namesOnPage));
      }
    }

    function save() {
      var saved = saveHidden(storage, hidden);
      if (unsavedNote) {
        unsavedNote.hidden = saved;
      }
    }

    each(boxes, function (box) {
      box.addEventListener("change", function () {
        var at = hidden.indexOf(box.value);
        if (box.checked && at >= 0) {
          hidden.splice(at, 1);
        } else if (!box.checked && at < 0) {
          hidden.push(box.value);
        }
        save();
        apply();
      });
    });

    var reset = panel.querySelector("[data-toggle-reset]");
    if (reset) {
      reset.addEventListener("click", function () {
        hidden = [];
        save();
        apply();
      });
    }

    apply();
    // 動く準備ができてから「表示するニュース項目を選ぶ」を出す。動かないブラウザでは出さず、全部表示のまま。
    panel.hidden = false;
  }

  // テスト（node）から上の決まりを確かめるための出口。ブラウザでは module が無いので何もしない。
  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      STORAGE_KEY: STORAGE_KEY,
      parseHidden: parseHidden,
      layoutItems: layoutItems,
      countHidden: countHidden,
      hiddenMessage: hiddenMessage,
    };
  }

  if (typeof document !== "undefined") {
    init();
  }
})();
