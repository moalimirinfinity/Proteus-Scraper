from scraper.parsing import SelectorSpec, parse_html


def test_parse_html_css_static_and_list() -> None:
    html = """
    <html>
      <body>
        <h1>Example Title</h1>
        <p class="summary">Short summary</p>
        <section>
          <article class="item">
            <a class="title" href="/item-1">Item One</a>
            <span class="price">1,234</span>
          </article>
          <article class="item">
            <a class="title" href="https://example.com/item-2">Item Two</a>
            <span class="price">2,345</span>
          </article>
        </section>
      </body>
    </html>
    """
    selectors = [
        SelectorSpec(field="title", selector="h1", data_type="string", required=True),
        SelectorSpec(field="summary", selector="p.summary", data_type="string", required=False),
        SelectorSpec(
            group_name="items",
            item_selector="article.item",
            field="name",
            selector="a.title",
            data_type="string",
            required=True,
        ),
        SelectorSpec(
            group_name="items",
            item_selector="article.item",
            field="url",
            selector="a.title",
            attribute="href",
            data_type="string",
            required=True,
        ),
        SelectorSpec(
            group_name="items",
            item_selector="article.item",
            field="price",
            selector="span.price",
            data_type="int",
            required=False,
        ),
    ]

    data, errors = parse_html(html, selectors, base_url="https://example.com/list")

    assert errors == []
    assert data["title"] == "Example Title"
    assert data["summary"] == "Short summary"
    assert data["items"] == [
        {
            "name": "Item One",
            "url": "https://example.com/item-1",
            "price": 1234,
        },
        {
            "name": "Item Two",
            "url": "https://example.com/item-2",
            "price": 2345,
        },
    ]


def test_parse_html_xpath_list() -> None:
    html = """
    <html>
      <body>
        <div id="main">
          <h1>XPath Title</h1>
          <ul id="items">
            <li>
              <a href="/x1">X One</a>
              <span class="price">10</span>
            </li>
            <li>
              <a href="/x2">X Two</a>
              <span class="price">20</span>
            </li>
          </ul>
        </div>
      </body>
    </html>
    """
    selectors = [
        SelectorSpec(field="title", selector="css:div#main h1", data_type="string", required=True),
        SelectorSpec(
            group_name="items",
            item_selector="xpath://ul[@id='items']/li",
            field="name",
            selector="xpath:.//a",
            data_type="string",
            required=True,
        ),
        SelectorSpec(
            group_name="items",
            item_selector="xpath://ul[@id='items']/li",
            field="url",
            selector="xpath:.//a",
            attribute="href",
            data_type="string",
            required=True,
        ),
        SelectorSpec(
            group_name="items",
            item_selector="xpath://ul[@id='items']/li",
            field="price",
            selector="xpath:.//span[@class='price']",
            data_type="int",
            required=False,
        ),
    ]

    data, errors = parse_html(html, selectors, base_url="https://example.com/list")

    assert errors == []
    assert data["title"] == "XPath Title"
    assert data["items"] == [
        {"name": "X One", "url": "https://example.com/x1", "price": 10},
        {"name": "X Two", "url": "https://example.com/x2", "price": 20},
    ]
