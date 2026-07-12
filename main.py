from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import json
import os
import re
import base64
import uuid
from datetime import datetime, timedelta
import httpx

# ============ CONFIGURATION ============
SHOPIFY_SHOP_DOMAIN = os.getenv("SHOPIFY_SHOP_DOMAIN", "your-store.myshopify.com")
SHOPIFY_ADMIN_API_TOKEN = os.getenv("SHOPIFY_ADMIN_API_TOKEN", "")
SHOPIFY_STOREFRONT_ACCESS_TOKEN = os.getenv("SHOPIFY_STOREFRONT_ACCESS_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

SHOPIFY_SHOP_DOMAIN = SHOPIFY_SHOP_DOMAIN.rstrip('/')

print("=" * 60)
print("CONFIG LOADED:")
print("  SHOPIFY_SHOP_DOMAIN:", SHOPIFY_SHOP_DOMAIN)
print("  ADMIN_TOKEN set:", bool(SHOPIFY_ADMIN_API_TOKEN))
print("  STOREFRONT_TOKEN set:", bool(SHOPIFY_STOREFRONT_ACCESS_TOKEN))
print("  OPENAI_KEY set:", bool(OPENAI_API_KEY))
print("=" * 60)

app = FastAPI(title="REZON AI VTON Engine", version="5.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ MODELS ============
class ChatMessage(BaseModel):
    role: str
    content: str

class SimpleChatRequest(BaseModel):
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

# ============ HTML STRIPPER ============
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
        self.admin_rest_url = f"https://{shop_domain}/admin/api/2024-07"
        self.storefront_url = f"https://{shop_domain}/api/2024-07/graphql.json"
        self.admin_headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": admin_token
        }
        self.storefront_headers = {
            "Content-Type": "application/json",
            "X-Shopify-Storefront-Access-Token": storefront_token
        }
        self._cached_categories = None
        self._cached_products = None

    def _calculate_discount(self, price_str, compare_str):
        try:
            price = float(price_str)
            compare = float(compare_str) if compare_str else 0
            if compare > price:
                return round(((compare - price) / compare) * 100)
        except:
            pass
        return 0

    def _get_category_from_product(self, p):
        """Auto-detect category from product_type and tags"""
        product_type = p.get("product_type", "").lower()
        tags = [t.lower() for t in p.get("tags", [])]
        title = p.get("title", "").lower()

        # Watches
        if any(k in product_type + str(tags) + title for k in ["watch", "watches", "timepiece", "wristwatch"]):
            return "watches"
        # Men's
        if any(k in product_type + str(tags) + title for k in ["men", "mens", "gent", "gentleman", "male"]):
            return "mens"
        # Women's
        if any(k in product_type + str(tags) + title for k in ["women", "womens", "ladies", "female", "girl"]):
            return "womens"
        # Perfumes
        if any(k in product_type + str(tags) + title for k in ["perfume", "fragrance", "oud", "scent", "cologne"]):
            return "perfumes"
        # Wallets/Accessories
        if any(k in product_type + str(tags) + title for k in ["wallet", "belt", "accessory", "accessories"]):
            return "accessories"
        # Clothing/Fabric
        if any(k in product_type + str(tags) + title for k in ["fabric", "suit", "kurta", "shalwar", "unstitched", "cloth"]):
            return "clothing"
        # Gift
        if any(k in product_type + str(tags) + title for k in ["gift", "box", "combo", "set"]):
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

        category = self._get_category_from_product(p)

        return {
            "id": f"gid://shopify/Product/{p['id']}",
            "title": p["title"],
            "description": strip_html(p.get("body_html", ""))[:300],
            "handle": p["handle"],
            "price": price,
            "compare_at_price": compare,
            "currency": "PKR",
            "image_url": image.get("src") if image else None,
            "variant_id": variant_id_gid,
            "numeric_variant_id": str(variant_id_num) if variant_id_num else None,
            "category": category,
            "tags": p.get("tags", []),
            "discount_percent": discount,
            "product_type": p.get("product_type", ""),
            "vendor": p.get("vendor", ""),
            "features": p.get("tags", [])[:4]
        }

    async def fetch_all_products(self, limit=50):
        """Fetch ALL real products from store"""
        if not self.admin_headers["X-Shopify-Access-Token"]:
            print("❌ ADMIN TOKEN NOT SET")
            return []

        url = f"{self.admin_rest_url}/products.json?limit={limit}&status=active"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.admin_headers, timeout=15.0)

            if response.status_code != 200:
                print(f"❌ Admin API Error {response.status_code}: {response.text[:200]}")
                return []

            data = response.json()
            products = data.get("products", [])

            if not products:
                print("⚠️ No products found in your Shopify store")
                return []

            formatted = [self._format_product(p) for p in products]
            self._cached_products = formatted

            print(f"✅ Fetched {len(formatted)} REAL products from your store!")
            for p in formatted[:3]:
                print(f"   - {p['title']} ({p['category']}) - {p['price']} PKR")
            return formatted

        except Exception as e:
            print(f"❌ Admin API error: {e}")
            return []

    async def get_categories(self):
        """Generate categories from REAL products"""
        products = await self.fetch_all_products(limit=50)

        if not products:
            return []

        # Group products by category
        categories_map = {}
        for p in products:
            cat = p.get("category", "other")
            if cat not in categories_map:
                categories_map[cat] = []
            categories_map[cat].append(p)

        # Build category list
        categories = []
        for cat_id, cat_products in categories_map.items():
            # Get first product image as category image
            first_img = None
            for p in cat_products:
                if p.get("image_url"):
                    first_img = p["image_url"]
                    break

            # Category display name
            display_names = {
                "watches": "Watches",
                "mens": "Men's Collection",
                "womens": "Women's Collection",
                "perfumes": "Perfumes",
                "accessories": "Accessories",
                "clothing": "Clothing",
                "gifts": "Gift Sets",
                "other": "Other Products"
            }

            categories.append({
                "id": cat_id,
                "name": display_names.get(cat_id, cat_id.title()),
                "image": first_img or "https://images.unsplash.com/photo-1558618666-fcd25c85f82e?w=400&h=400&fit=crop",
                "product_count": len(cat_products)
            })

        self._cached_categories = categories
        print(f"✅ Generated {len(categories)} categories from real products: {[c['name'] for c in categories]}")
        return categories

    async def fetch_products_by_category(self, category, limit=10):
        """Fetch products by category"""
        products = await self.fetch_all_products(limit=50)

        if not products:
            return []

        filtered = [p for p in products if p.get("category") == category]
        return filtered[:limit]

    async def get_product_by_id(self, product_id):
        """Get single product by ID or handle"""
        products = await self.fetch_all_products(limit=50)

        for p in products:
            if p["id"] == product_id or p["handle"] == product_id:
                return p

        return None

    async def create_cart(self, variant_id, quantity=1):
        if not self.storefront_headers["X-Shopify-Storefront-Access-Token"]:
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
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.storefront_url,
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

    def _build_product_detail_prompt(self, product):
        features = product.get("features", [])
        features_text = "\n".join([f"- {f}" for f in features]) if features else ""

        discount_text = ""
        if product.get("discount_percent", 0) > 0:
            discount_text = f"\n🔥 SPECIAL OFFER: {product['discount_percent']}% OFF! Original price {product.get('compare_at_price', '')} PKR, now only {product['price']} PKR!"

        return f"""Product: {product['title']}
Category: {product.get('product_type', 'General')}
Price: {product['price']} PKR{discount_text}
Description: {product.get('description', '')}
Features/Tags:
{features_text}

Explain this product in Roman Urdu like a friendly salesman. Highlight:
1. Product quality and brand value
2. Best use cases (occasion, season, gifting)
3. Why it's worth buying
4. Discount value (if any) - EXCITEDLY mention!
5. End with "Add to Cart karein?" and emojis

Keep it under 150 words, exciting and persuasive."""

    async def explain_product(self, product):
        prompt = self._build_product_detail_prompt(product)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.url,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": "You are REZON AI, a premium fashion assistant. Speak in Roman Urdu (Hinglish). Be friendly, persuasive, and concise."},
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
            return self._fallback_explanation(product)

        except Exception as e:
            print(f"AI explain error: {e}")
            return self._fallback_explanation(product)

    def _fallback_explanation(self, product):
        title = product.get("title", "")
        price = product.get("price", "")
        compare = product.get("compare_at_price", "")
        discount = product.get("discount_percent", 0)
        desc = product.get("description", "")[:100]
        ptype = product.get("product_type", "")

        msg = f"Yeh hamara {title} hai! "
        if ptype:
            msg += f"Category: {ptype}. "
        if desc:
            msg += f"{desc} "

        if discount > 0 and compare:
            msg += f"🔥 Abhi {discount}% OFF par mil raha hai! Sirf {price} PKR (was {compare} PKR). "
        else:
            msg += f"Price sirf {price} PKR. "

        msg += "Quality bohat zabardast hai. Add to Cart karein? 🛒"
        return msg

    async def chat_with_products(self, messages, products=None, force_products=False):
        system_prompt = "You are REZON AI, a premium fashion assistant for REZON store. Speak in Roman Urdu (Hinglish). Be friendly, concise, and helpful."

        formatted_messages = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            if isinstance(msg, dict):
                formatted_messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
            else:
                formatted_messages.append({"role": msg.role, "content": msg.content})

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.url,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": formatted_messages,
                        "temperature": 0.7,
                        "max_tokens": 500
                    },
                    timeout=20.0
                )

            result = response.json()
            if "choices" not in result:
                return {"text": "Sorry, AI service temporarily unavailable.", "tool_calls": None}

            message = result["choices"][0]["message"]
            return {"text": message.get("content", ""), "tool_calls": message.get("tool_calls")}

        except Exception as e:
            print("OpenAI error:", str(e))
            return {"text": "Sorry, AI service mein masla hai.", "tool_calls": None}

ai_service = AIService(OPENAI_API_KEY)

# ============ API ROUTES ============

@app.get("/")
async def root():
    return {"message": "REZON AI VTON Engine Running", "version": "5.0.0", "status": "ok"}

@app.get("/api/categories")
async def get_categories():
    """Return REAL categories from store products"""
    try:
        categories = await shopify.get_categories()
        return {"success": True, "categories": categories}
    except Exception as e:
        print(f"Categories error: {e}")
        return {"success": False, "error": str(e), "categories": []}

@app.post("/api/products")
async def get_products(request: ProductFetchRequest):
    """Return REAL products by category"""
    try:
        products = await shopify.fetch_products_by_category(request.category, limit=request.limit)
        return {"success": True, "products": products, "category": request.category}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/product/explain")
async def explain_product_endpoint(request: ProductFetchRequest):
    """Get AI explanation for a specific product"""
    try:
        product = await shopify.get_product_by_id(request.product_id)

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
async def add_to_cart(request: AddToCartRequest):
    try:
        result = await shopify.create_cart(request.variant_id, request.quantity)

        if "error" not in result:
            cart_data = result.get("data", {}).get("cartCreate", {})
            cart = cart_data.get("cart", {})
            if cart.get("checkoutUrl"):
                return JSONResponse(content={
                    "success": True,
                    "cart_id": cart.get("id"),
                    "checkout_url": cart.get("checkoutUrl"),
                    "message": "Product cart mein add ho gaya! Checkout karein.",
                    "action": "checkout"
                })

        # Fallback: Direct Shopify cart URL
        variant_id = request.variant_id
        if variant_id.startswith("gid://"):
            variant_id = variant_id.split("/")[-1]

        product = await shopify.get_product_by_id(request.variant_id)
        handle = product.get("handle", "") if product else ""

        cart_url = f"https://{SHOPIFY_SHOP_DOMAIN}/cart/add?id={variant_id}&quantity={request.quantity}"
        product_url = f"https://{SHOPIFY_SHOP_DOMAIN}/products/{handle}" if handle else cart_url

        return JSONResponse(content={
            "success": True,
            "checkout_url": cart_url,
            "product_url": product_url,
            "message": "✅ Product cart mein add ho gaya! Neeche diye gaye button se checkout karein.",
            "action": "cart"
        })

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": "Cart add failed", "error": str(e)})

@app.post("/api/chat-simple")
async def chat_simple(request: SimpleChatRequest):
    try:
        messages = [{"role": "user", "content": request.message}]

        product_keywords = ["product", "buy", "price", "watch", "watches", "men", "women", "perfume",
                           "wallet", "kapra", "cheez", "suit", "clothes", "fashion", "len", "lena",
                           "purchase", "dikhao", "show", "lawn", "fabric", "gift", "box", "wear",
                           "unstitched", "dikhayo", "brand", "original"]
        needs_products = any(kw in request.message.lower() for kw in product_keywords)

        products = []
        if needs_products:
            try:
                products = await shopify.fetch_all_products(limit=6)
            except Exception as e:
                print("Product fetch error:", e)

        ai_response = await ai_service.chat_with_products(messages, products, force_products=needs_products and len(products) > 0)

        if needs_products:
            if len(products) == 0:
                products = []

            return JSONResponse(content={
                "success": True,
                "response": ai_response.get("text") or "Yeh hain hamare best products!",
                "product_cards": products,
                "quick_replies": ["Categories dekhein", "Discount code chahiye", "New arrivals"],
                "session_id": request.session_id
            })

        return JSONResponse(content={
            "success": True,
            "response": ai_response.get("text") or "Main aapki madad karne ke liye tayyar hoon!",
            "product_cards": None,
            "quick_replies": ["Categories dekhein", "Styling tips chahiye", "Discount code"],
            "session_id": request.session_id
        })

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "response": "Kuch galat ho gaya.", "error": str(e)})

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
