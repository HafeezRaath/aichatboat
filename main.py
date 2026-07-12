from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List
import os
import re
import httpx
from urllib.parse import urlparse

# ============ CONFIGURATION ============
SHOPIFY_SHOP_DOMAIN = os.getenv("SHOPIFY_SHOP_DOMAIN", "your-store.myshopify.com")
SHOPIFY_ADMIN_API_TOKEN = os.getenv("SHOPIFY_ADMIN_API_TOKEN", "")
SHOPIFY_STOREFRONT_ACCESS_TOKEN = os.getenv("SHOPIFY_STOREFRONT_ACCESS_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Clean domain
SHOPIFY_SHOP_DOMAIN = SHOPIFY_SHOP_DOMAIN.rstrip('/').replace("https://", "").replace("http://", "")

print("=" * 60)
print("REZON AI CONFIG:")
print("  SHOP_DOMAIN:", SHOPIFY_SHOP_DOMAIN)
print("  ADMIN_TOKEN:", "SET" if SHOPIFY_ADMIN_API_TOKEN else "MISSING")
print("  STOREFRONT_TOKEN:", "SET" if SHOPIFY_STOREFRONT_ACCESS_TOKEN else "MISSING")
print("  OPENAI_KEY:", "SET" if OPENAI_API_KEY else "MISSING")
print("=" * 60)

app = FastAPI(title="REZON AI Engine", version="6.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ MODELS ============
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"

class ProductFetchRequest(BaseModel):
    query: Optional[str] = None
    product_id: Optional[str] = None
    category: Optional[str] = None
    limit: int = 10

class AddToCartRequest(BaseModel):
    variant_id: str
    quantity: int = 1

# ============ HELPERS ============
def strip_html(html_text):
    if not html_text:
        return ""
    clean = re.sub(r'<[^>]+>', '', html_text)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean

# ============ SHOPIFY CLIENT ============
class ShopifyClient:
    def __init__(self, shop_domain, admin_token, storefront_token):
        self.shop_domain = shop_domain
        self.admin_token = admin_token
        self.storefront_token = storefront_token
        
        # These will be resolved if domain redirects
        self._admin_base_url = None
        self._storefront_url = None
        
        self.admin_headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": admin_token
        }
        self.storefront_headers = {
            "Content-Type": "application/json",
            "X-Shopify-Storefront-Access-Token": storefront_token
        }
        self._cached_products = None

    def _get_admin_base(self):
        if self._admin_base_url:
            return self._admin_base_url
        return f"https://{self.shop_domain}/admin/api/2024-07"

    def _get_storefront_url(self):
        if self._storefront_url:
            return self._storefront_url
        return f"https://{self.shop_domain}/api/2024-07/graphql.json"

    async def _admin_request(self, endpoint):
        """Make admin request with manual redirect handling"""
        base_url = self._get_admin_base()
        url = f"{base_url}{endpoint}"
        
        async with httpx.AsyncClient() as client:
            # First try without redirects
            response = await client.get(url, headers=self.admin_headers, timeout=15.0, follow_redirects=False)
            
            # Handle 301/302 manually to preserve auth headers
            if response.status_code in (301, 302, 307, 308):
                location = response.headers.get('location')
                if location:
                    print(f"🔀 Redirect detected: {location}")
                    # Parse new base URL
                    parsed = urlparse(location)
                    new_base = f"{parsed.scheme}://{parsed.netloc}/admin/api/2024-07"
                    self._admin_base_url = new_base
                    print(f"✅ Resolved admin base: {new_base}")
                    
                    # Retry with resolved URL
                    url = f"{new_base}{endpoint}"
                    response = await client.get(url, headers=self.admin_headers, timeout=15.0)
            
            return response

    def _calculate_discount(self, price_str, compare_str):
        try:
            price = float(price_str)
            compare = float(compare_str) if compare_str else 0
            if compare > price:
                return round(((compare - price) / compare) * 100)
        except:
            pass
        return 0

    def _get_category(self, p):
        product_type = p.get("product_type", "").lower()
        tags = [t.lower() for t in p.get("tags", [])]
        title = p.get("title", "").lower()
        vendor = p.get("vendor", "").lower()
        all_text = f"{product_type} {' '.join(tags)} {title} {vendor}"

        if any(k in all_text for k in ["women", "womens", "ladies", "female", "girl", "kaftan", "kurta", "shalwar", "kameez", "dress", "stitched", "unstitched", "lawn", "cotton", "fabric"]):
            return "womens"
        if any(k in all_text for k in ["men", "mens", "gent", "gentleman", "male", "boys"]):
            return "mens"
        if any(k in all_text for k in ["watch", "watches", "timepiece", "wristwatch"]):
            return "watches"
        if any(k in all_text for k in ["perfume", "fragrance", "oud", "scent", "cologne", "attar"]):
            return "perfumes"
        if any(k in all_text for k in ["wallet", "belt", "accessory", "accessories", "bag", "handbag"]):
            return "accessories"
        if any(k in all_text for k in ["gift", "box", "combo", "set", "bundle"]):
            return "gifts"
        return product_type if product_type else "other"

    def _format_product(self, p):
        variant = p["variants"][0] if p.get("variants") else {}
        image = p["images"][0] if p.get("images") else {}

        price = variant.get("price", "0.00")
        compare = variant.get("compare_at_price")
        discount = self._calculate_discount(price, compare)

        variant_id_num = variant.get("id")
        variant_id_gid = f"gid://shopify/ProductVariant/{variant_id_num}" if variant_id_num else None

        inventory_qty = variant.get("inventory_quantity", 0)
        available = inventory_qty > 0

        images = [img.get("src") for img in p.get("images", []) if img.get("src")]

        return {
            "id": f"gid://shopify/Product/{p['id']}",
            "title": p["title"],
            "description": strip_html(p.get("body_html", ""))[:300],
            "handle": p["handle"],
            "price": price,
            "compare_at_price": compare,
            "currency": "PKR",
            "image_url": image.get("src") if image else None,
            "images": images,
            "variant_id": variant_id_gid,
            "numeric_variant_id": str(variant_id_num) if variant_id_num else None,
            "category": self._get_category(p),
            "tags": p.get("tags", []),
            "discount_percent": discount,
            "product_type": p.get("product_type", ""),
            "vendor": p.get("vendor", ""),
            "features": p.get("tags", [])[:4],
            "available": available
        }

    async def fetch_all_products(self, limit=50):
        if not self.admin_token:
            print("ADMIN TOKEN NOT SET")
            return []

        endpoint = f"/products.json?limit={limit}&status=active"
        print(f"Fetching admin endpoint: {endpoint}")

        try:
            response = await self._admin_request(endpoint)
            print(f"Status: {response.status_code}")

            if response.status_code == 401:
                print("ERROR 401: Token invalid")
                return []
            if response.status_code == 403:
                print("ERROR 403: Token lacks permissions")
                return []
            if response.status_code != 200:
                print(f"ERROR {response.status_code}: {response.text[:500]}")
                return []

            data = response.json()
            products = data.get("products", [])
            print(f"Found {len(products)} raw products")

            if not products:
                return []

            formatted = [self._format_product(p) for p in products]
            self._cached_products = formatted
            
            for p in formatted[:3]:
                print(f"   ✅ {p['title']} | {p['category']} | Rs.{p['price']} | Available: {p['available']}")
            
            return formatted

        except Exception as e:
            print(f"Fetch error: {e}")
            import traceback
            traceback.print_exc()
            return []

    async def get_categories(self):
        products = await self.fetch_all_products(limit=50)
        if not products:
            print("No products found for categories")
            return []

        categories_map = {}
        for p in products:
            cat = p.get("category", "other")
            categories_map.setdefault(cat, []).append(p)

        display_names = {
            "womens": "Women's Collection",
            "mens": "Men's Collection",
            "watches": "Watches",
            "perfumes": "Perfumes",
            "accessories": "Accessories",
            "gifts": "Gift Sets",
            "other": "Other Products"
        }

        categories = []
        for cat_id, cat_products in categories_map.items():
            first_img = next((p.get("image_url") for p in cat_products if p.get("image_url")), None)
            categories.append({
                "id": cat_id,
                "name": display_names.get(cat_id, cat_id.title()),
                "image": first_img or "https://images.unsplash.com/photo-1558618666-fcd25c85f82e?w=400&h=400&fit=crop",
                "product_count": len(cat_products)
            })

        print(f"Categories: {[c['name'] for c in categories]}")
        return categories

    async def fetch_products_by_category(self, category, limit=10):
        products = await self.fetch_all_products(limit=50)
        if not products:
            return []
        filtered = [p for p in products if p.get("category") == category]
        return filtered[:limit]

    async def get_product_by_id(self, product_id):
        products = await self.fetch_all_products(limit=50)
        for p in products:
            if p["id"] == product_id or p["handle"] == product_id:
                return p
        return None

    async def create_cart(self, variant_id, quantity=1):
        if not self.storefront_token:
            return {"error": "No storefront token"}

        mutation = """
        mutation cartCreate($input: CartInput!) {
            cartCreate(input: $input) {
                cart { id checkoutUrl }
                userErrors { field message }
            }
        }
        """
        variables = {"input": {"lines": [{"quantity": quantity, "merchandiseId": variant_id}]}}

        try:
            url = self._get_storefront_url()
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=self.storefront_headers,
                    json={"query": mutation, "variables": variables},
                    timeout=10.0
                )
                return response.json()
        except Exception as e:
            return {"error": str(e)}

shopify = ShopifyClient(SHOPIFY_SHOP_DOMAIN, SHOPIFY_ADMIN_API_TOKEN, SHOPIFY_STOREFRONT_ACCESS_TOKEN)

# ============ AI SERVICE ============
class AIService:
    def __init__(self, api_key):
        self.api_key = api_key
        self.url = "https://api.openai.com/v1/chat/completions"

    def _build_prompt(self, product):
        features = product.get("features", [])
        features_text = "\n".join([f"- {f}" for f in features]) if features else ""
        discount_text = ""
        if product.get("discount_percent", 0) > 0:
            discount_text = f"\n🔥 OFFER: {product['discount_percent']}% OFF! Original Rs.{product.get('compare_at_price', '')}, now Rs.{product['price']}!"
        availability = "In Stock" if product.get("available", True) else "Sold Out"

        return f"""Product: {product['title']}
Category: {product.get('product_type', 'General')}
Price: Rs.{product['price']}{discount_text}
Availability: {availability}
Description: {product.get('description', '')}
Features:
{features_text}

Explain in Roman Urdu like a friendly salesman. Keep under 150 words. End with "Add to Cart karein?" """

    async def explain_product(self, product):
        if not self.api_key:
            return self._fallback(product)

        prompt = self._build_prompt(product)
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.url,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": "You are REZON AI, a premium fashion assistant. Speak in Roman Urdu (Hinglish). Be friendly and persuasive."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.7,
                        "max_tokens": 300
                    },
                    timeout=15.0
                )
            result = response.json()
            if "choices" in result:
                return result["choices"][0]["message"].get("content", "")
            return self._fallback(product)
        except Exception as e:
            print(f"AI error: {e}")
            return self._fallback(product)

    def _fallback(self, product):
        msg = f"Yeh hamara {product['title']} hai! "
        if product.get("discount_percent", 0) > 0 and product.get("compare_at_price"):
            msg += f"🔥 {product['discount_percent']}% OFF! Sirf Rs.{product['price']} (was Rs.{product['compare_at_price']}). "
        else:
            msg += f"Price: Rs.{product['price']}. "
        if not product.get("available", True):
            msg += "Sold Out! "
        else:
            msg += "Quality zabardast hai. Add to Cart karein? 🛒"
        return msg

    async def chat(self, messages):
        if not self.api_key:
            return {"text": "AI service unavailable.", "tool_calls": None}

        system_prompt = "You are REZON AI, a premium fashion assistant. Speak in Roman Urdu (Hinglish). Be friendly and concise."
        formatted = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            formatted.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.url,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": formatted,
                        "temperature": 0.7,
                        "max_tokens": 500
                    },
                    timeout=20.0
                )
            result = response.json()
            if "choices" not in result:
                return {"text": "AI service busy.", "tool_calls": None}
            msg = result["choices"][0]["message"]
            return {"text": msg.get("content", ""), "tool_calls": msg.get("tool_calls")}
        except Exception as e:
            return {"text": "AI service mein masla hai.", "tool_calls": None}

ai_service = AIService(OPENAI_API_KEY)

# ============ API ROUTES ============

@app.get("/")
async def root():
    return {"message": "REZON AI Running", "version": "6.3.0", "status": "ok"}

# DEBUG ENDPOINTS
@app.get("/api/debug/config")
async def debug_config():
    return {
        "shop_domain": SHOPIFY_SHOP_DOMAIN,
        "admin_token_set": bool(SHOPIFY_ADMIN_API_TOKEN),
        "admin_token_prefix": SHOPIFY_ADMIN_API_TOKEN[:10] + "..." if SHOPIFY_ADMIN_API_TOKEN else None,
        "storefront_token_set": bool(SHOPIFY_STOREFRONT_ACCESS_TOKEN),
        "openai_key_set": bool(OPENAI_API_KEY)
    }

@app.get("/api/debug/test-admin")
async def test_admin():
    if not SHOPIFY_ADMIN_API_TOKEN:
        return {"success": False, "error": "No admin token"}
    
    try:
        response = await shopify._admin_request("/products.json?limit=1")
        return {
            "success": response.status_code == 200,
            "status_code": response.status_code,
            "resolved_base": shopify._admin_base_url,
            "preview": response.text[:500]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/debug/shop-info")
async def shop_info():
    if not SHOPIFY_ADMIN_API_TOKEN:
        return {"success": False, "error": "No admin token"}
    
    try:
        response = await shopify._admin_request("/shop.json")
        if response.status_code == 200:
            return {"success": True, "shop": response.json().get("shop", {})}
        return {"success": False, "status_code": response.status_code, "error": response.text[:500]}
    except Exception as e:
        return {"success": False, "error": str(e)}

# MAIN ENDPOINTS
@app.get("/api/categories")
async def get_categories():
    try:
        cats = await shopify.get_categories()
        return {"success": True, "categories": cats}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e), "categories": []}

@app.post("/api/products")
async def get_products(req: ProductFetchRequest):
    try:
        products = await shopify.fetch_products_by_category(req.category, limit=req.limit)
        return {"success": True, "products": products, "category": req.category}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/product/explain")
async def explain_product(req: ProductFetchRequest):
    try:
        product = await shopify.get_product_by_id(req.product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        explanation = await ai_service.explain_product(product)
        return {
            "success": True,
            "product": product,
            "explanation": explanation,
            "quick_replies": ["Add to Cart", "Aur products dekhein", "Discount code chahiye", "Styling tips"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/cart/add")
async def add_to_cart(req: AddToCartRequest):
    try:
        result = await shopify.create_cart(req.variant_id, req.quantity)
        if "error" not in result:
            cart_data = result.get("data", {}).get("cartCreate", {})
            cart = cart_data.get("cart", {})
            if cart.get("checkoutUrl"):
                return JSONResponse(content={
                    "success": True,
                    "cart_id": cart.get("id"),
                    "checkout_url": cart.get("checkoutUrl"),
                    "message": "Product cart mein add ho gaya!"
                })

        # Fallback
        variant_id = req.variant_id
        if variant_id.startswith("gid://"):
            variant_id = variant_id.split("/")[-1]
        product = await shopify.get_product_by_id(req.variant_id)
        handle = product.get("handle", "") if product else ""
        cart_url = f"https://{SHOPIFY_SHOP_DOMAIN}/cart/add?id={variant_id}&quantity={req.quantity}"
        product_url = f"https://{SHOPIFY_SHOP_DOMAIN}/products/{handle}" if handle else cart_url

        return JSONResponse(content={
            "success": True,
            "checkout_url": cart_url,
            "product_url": product_url,
            "message": "Product cart mein add ho gaya! Checkout karein."
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

@app.post("/api/chat-simple")
async def chat_simple(req: ChatRequest):
    try:
        messages = [{"role": "user", "content": req.message}]
        keywords = ["product", "buy", "price", "watch", "watches", "men", "women", "perfume",
                   "wallet", "kapra", "cheez", "suit", "clothes", "fashion", "len", "lena",
                   "purchase", "dikhao", "show", "lawn", "fabric", "gift", "box", "wear",
                   "unstitched", "dikhayo", "brand", "original", "kaftan", "kurta", "dress",
                   "stitched", "ladies", "girl"]
        needs_products = any(kw in req.message.lower() for kw in keywords)

        products = []
        if needs_products:
            try:
                products = await shopify.fetch_all_products(limit=6)
            except Exception as e:
                print("Product fetch error:", e)

        ai_response = await ai_service.chat(messages)

        return JSONResponse(content={
            "success": True,
            "response": ai_response.get("text") or "Main aapki madad karne ke liye tayyar hoon!",
            "product_cards": products if needs_products else None,
            "quick_replies": ["Categories dekhein", "Discount code chahiye", "New arrivals"],
            "session_id": req.session_id
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
